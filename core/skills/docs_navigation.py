"""
DocsNavigationSkill — Level 2 web capability.

Triggers on "how do I do X with Y framework" or "show me docs about X".
1. Searches the web for the right docs page
2. Fetches it
3. Follows up to 3 same-domain links matching the user's topic
4. Synthesizes a complete answer using all pages, citing each
"""
from __future__ import annotations
import asyncio, re
from typing import AsyncIterator

from core.skills.base import Skill, SkillContext, SkillEvent
from core.generator    import stream as llm_stream
from core.web_search   import _ddg_search
from core.web_navigator import crawl, score_source, fetch_smart
from core.skills._synthesize import synthesize


# Canonical docs roots for major frameworks. We try these FIRST so we don't
# depend on DDG returning a fresh URL. The crawler then follows internal links.
_KNOWN_DOCS_ROOTS = {
    # Python ecosystem
    "fastapi":    ["https://fastapi.tiangolo.com/"],
    "pydantic":   ["https://docs.pydantic.dev/latest/",
                   "https://docs.pydantic.dev/latest/concepts/validators/"],
    "python":     ["https://docs.python.org/3/"],
    "django":     ["https://docs.djangoproject.com/en/stable/"],
    "flask":      ["https://flask.palletsprojects.com/en/stable/"],
    "sqlalchemy": ["https://docs.sqlalchemy.org/en/20/"],
    "pytorch":    ["https://pytorch.org/docs/stable/"],
    "tensorflow": ["https://www.tensorflow.org/api_docs"],
    "huggingface":["https://huggingface.co/docs"],
    "langchain":  ["https://python.langchain.com/docs/"],
    "numpy":      ["https://numpy.org/doc/stable/"],
    "pandas":     ["https://pandas.pydata.org/docs/"],
    "pytest":     ["https://docs.pytest.org/en/stable/"],
    "celery":     ["https://docs.celeryq.dev/en/stable/"],
    "asyncio":    ["https://docs.python.org/3/library/asyncio.html"],
    "httpx":      ["https://www.python-httpx.org/"],
    "requests":   ["https://requests.readthedocs.io/en/latest/"],
    # JS / Web
    "react":      ["https://react.dev/learn", "https://react.dev/reference/react"],
    "nextjs":     ["https://nextjs.org/docs"],
    "next":       ["https://nextjs.org/docs"],
    "vue":        ["https://vuejs.org/guide/introduction.html"],
    "svelte":     ["https://svelte.dev/docs"],
    "sveltekit":  ["https://svelte.dev/docs/kit"],
    "nuxt":       ["https://nuxt.com/docs"],
    "remix":      ["https://remix.run/docs"],
    "astro":      ["https://docs.astro.build/"],
    "express":    ["https://expressjs.com/"],
    "nestjs":     ["https://docs.nestjs.com/"],
    "nest":       ["https://docs.nestjs.com/"],
    "node":       ["https://nodejs.org/en/docs"],
    "nodejs":     ["https://nodejs.org/en/docs"],
    "deno":       ["https://docs.deno.com/"],
    "bun":        ["https://bun.sh/docs"],
    "typescript": ["https://www.typescriptlang.org/docs/"],
    "javascript": ["https://developer.mozilla.org/en-US/docs/Web/JavaScript"],
    "prisma":     ["https://www.prisma.io/docs"],
    "drizzle":    ["https://orm.drizzle.team/docs/overview"],
    "tailwind":   ["https://tailwindcss.com/docs"],
    "tailwindcss":["https://tailwindcss.com/docs"],
    "shadcn":     ["https://ui.shadcn.com/docs"],
    "chakra":     ["https://chakra-ui.com/docs/components"],
    "mui":        ["https://mui.com/material-ui/getting-started/"],
    "vite":       ["https://vitejs.dev/guide/"],
    "webpack":    ["https://webpack.js.org/concepts/"],
    "htmx":       ["https://htmx.org/docs/"],
    "zod":        ["https://zod.dev/"],
    "tanstack":   ["https://tanstack.com/query/latest/docs"],
    # Systems / infra
    "rust":       ["https://doc.rust-lang.org/book/", "https://doc.rust-lang.org/std/"],
    "go":         ["https://go.dev/doc/", "https://pkg.go.dev/"],
    "golang":     ["https://go.dev/doc/"],
    "kotlin":     ["https://kotlinlang.org/docs/home.html"],
    "swift":      ["https://www.swift.org/documentation/"],
    "java":       ["https://docs.oracle.com/en/java/"],
    "docker":     ["https://docs.docker.com/"],
    "kubernetes": ["https://kubernetes.io/docs/"],
    "k8s":        ["https://kubernetes.io/docs/"],
    "terraform":  ["https://developer.hashicorp.com/terraform/docs"],
    "ansible":    ["https://docs.ansible.com/ansible/latest/"],
    # Databases
    "postgres":   ["https://www.postgresql.org/docs/current/"],
    "postgresql": ["https://www.postgresql.org/docs/current/"],
    "mysql":      ["https://dev.mysql.com/doc/"],
    "sqlite":     ["https://www.sqlite.org/docs.html"],
    "redis":      ["https://redis.io/docs/latest/"],
    "mongodb":    ["https://www.mongodb.com/docs/"],
    # Cloud
    "aws":        ["https://docs.aws.amazon.com/"],
    "gcp":        ["https://cloud.google.com/docs"],
    "azure":      ["https://learn.microsoft.com/en-us/azure/"],
    "vercel":     ["https://vercel.com/docs"],
    "netlify":    ["https://docs.netlify.com/"],
    "cloudflare": ["https://developers.cloudflare.com/"],
    "supabase":   ["https://supabase.com/docs"],
    # AI / LLM
    "ollama":     ["https://github.com/ollama/ollama/blob/main/README.md",
                   "https://ollama.com/library"],
    "anthropic":  ["https://docs.anthropic.com/"],
    "openai":     ["https://platform.openai.com/docs/overview"],
    "llama":      ["https://www.llama.com/docs/overview/"],
}


# Triggers for documentation queries (how-to + framework, or "docs on X")
_DOCS_TRIGGER_RE = re.compile(
    r"\b(how\s+do\s+i|how\s+to|how\s+can\s+i|show\s+me\s+(?:the\s+)?docs?|"
    r"documentation\s+(?:on|for|about)|"
    r"docs?\s+(?:on|for|about)|"
    r"tutorial\s+(?:on|for|about)|"
    r"guide\s+(?:on|for|about)|"
    r"reference\s+(?:on|for|about)|"
    r"deep\s+dive\s+(?:on|into))\b",
    re.I,
)

# Framework / tool keywords — having one strengthens the docs-intent signal
_FRAMEWORK_RE = re.compile(
    r"\b(fastapi|django|flask|rails|spring|laravel|express|nest(?:js)?|"
    r"react|vue|angular|svelte(?:kit)?|next(?:js)?|nuxt|remix|astro|htmx|"
    r"pydantic|sqlalchemy|prisma|drizzle|tanstack|zod|"
    r"tailwind(?:css)?|chakra|bootstrap|mui|shadcn|vite|webpack|"
    r"docker|kubernetes|k8s|terraform|ansible|"
    r"aws|gcp|azure|cloudflare|vercel|netlify|supabase|"
    r"python|javascript|typescript|rust|golang|go|java|kotlin|swift|"
    r"postgres(?:ql)?|mysql|sqlite|mongodb|redis|"
    r"node(?:js)?|deno|bun|"
    r"pytorch|tensorflow|huggingface|langchain|llama|ollama|anthropic|openai|"
    r"numpy|pandas|pytest|celery|httpx|requests|asyncio)\b",
    re.I,
)


_DOCS_SYSTEM = """You are a technical documentation assistant. You have fetched up to 3 documentation pages on the user's topic.

CRITICAL RULES:
1. Answer using ONLY the source content below.
2. Cite ONLY source numbers that ACTUALLY APPEAR below. If only [1] is given, do NOT
   reference [2] or [3]. Do NOT invent sources.
3. If the sources don't cover the user's question (e.g., they're outdated or off-topic),
   say so explicitly: "The available docs don't cover this — they only show [topic]."
   Do NOT fall back on training knowledge or invent API methods.
4. Show code examples ONLY when the docs include them. Copy syntax exactly — don't
   change `@field_validator` to `@validator` or vice versa.
5. Format: short intro → code snippet (if available) → bullet explanation → gotchas.
6. NEVER invent API methods, decorators, or function signatures not in the sources.
"""

_DOCS_USER = """User's question:
{query}

Documentation pages (cite as [N]):
{sources}

Now answer."""


class DocsNavigationSkill(Skill):
    name        = "docs_navigation"
    label       = "Docs deep dive"
    description = "Searches official docs, follows internal links, synthesizes a complete answer"
    priority    = 14   # before web_search (15), after compare/fetch

    def matches(self, ctx: SkillContext) -> bool:
        has_docs_intent = bool(_DOCS_TRIGGER_RE.search(ctx.query))
        has_framework  = bool(_FRAMEWORK_RE.search(ctx.query))
        # Require BOTH a how-to intent AND a known framework name, OR an explicit
        # "show me docs / documentation on X" phrasing.
        return has_docs_intent and has_framework

    async def execute(self, ctx: SkillContext) -> AsyncIterator[SkillEvent]:
        query = ctx.query

        # Phase 1: pick the docs root.
        # Strategy: try CANONICAL URL for the framework first (most reliable),
        #           fall back to DDG search only if canonical isn't known.
        yield SkillEvent(kind="status", content={
            "skill": self.name, "label": self.label,
            "stage": "searching", "query": query,
        })

        framework_match = _FRAMEWORK_RE.search(query)
        fw = framework_match.group(0).lower() if framework_match else ""
        canonical_roots = _KNOWN_DOCS_ROOTS.get(fw, [])

        # Pick which root to try first. Prefer canonical URLs we KNOW are live.
        candidate_urls: list[str] = list(canonical_roots)
        # Also do a DDG search to find topic-specific deep links
        site_hint_map = {
            "fastapi": "site:fastapi.tiangolo.com",
            "pydantic": "site:docs.pydantic.dev/latest",
            "react": "site:react.dev",
            "next": "site:nextjs.org", "nextjs": "site:nextjs.org",
            "rust": "site:doc.rust-lang.org",
            "python": "site:docs.python.org",
            "django": "site:djangoproject.com",
            "tailwind": "site:tailwindcss.com",
            "tailwindcss": "site:tailwindcss.com",
        }
        site_hint = site_hint_map.get(fw, "")
        ddg_results = _ddg_search(f"{site_hint} {query}".strip(), max_results=4)
        for r in ddg_results:
            url = r.get("url", "")
            if url.startswith("http") and url not in candidate_urls:
                candidate_urls.append(url)

        if not candidate_urls:
            yield SkillEvent(kind="answer_chunk",
                              content="Couldn't find documentation pages for that query. "
                                       "Try naming the framework explicitly.")
            yield SkillEvent(kind="done", content={"skill": self.name, "ok": False})
            return

        # Phase 2: crawl. Try each candidate root until one gives real content.
        topic_kws = [w for w in re.findall(r'\b[a-zA-Z]{4,}\b', query)
                     if w.lower() not in {'how', 'what', 'why', 'show', 'docs',
                                          'documentation', 'tutorial', 'guide',
                                          'reference', 'about', 'find', 'with',
                                          'them', 'this', 'that', 'have', 'using'}][:6]

        yield SkillEvent(kind="status", content={
            "skill": self.name, "stage": "crawling",
            "root": candidate_urls[0], "max_pages": 3,
            "candidates": len(candidate_urls),
        })

        pages = []
        async def _on_progress(ev): pass

        # Try canonical roots first, stop as soon as we get real content
        for root_url in candidate_urls[:4]:
            try:
                pages = await crawl(root_url, topic_keywords=topic_kws, max_pages=3,
                                     on_progress=_on_progress)
                # Filter out empty/error pages
                pages = [p for p in pages if p.get("content") and len(p["content"]) > 200]
                if pages:
                    break
            except Exception:
                continue

        if not pages:
            yield SkillEvent(kind="answer_chunk",
                              content=f"I tried {len(candidate_urls)} candidate docs URLs but "
                                       f"couldn't read real content from any. The pages may have "
                                       f"moved, or the docs site is unreachable. Try a more "
                                       f"specific search query.")
            yield SkillEvent(kind="done", content={"skill": self.name, "ok": False,
                                                    "candidates_tried": min(4, len(candidate_urls))})
            return

        yield SkillEvent(kind="status", content={
            "skill": self.name, "stage": "synthesizing",
            "pages_read": len(pages),
            "urls": [p["url"] for p in pages],
        })

        # Phase 3: feed all pages to the LLM, ranked by score
        pages.sort(key=lambda p: -p["score"])
        sources_block = "\n\n".join(
            f"--- Source [{i + 1}] (score {p['score']}/100): {p['url']} ---\n{p['content'][:2800]}"
            for i, p in enumerate(pages[:3])
        )

        async for ev in synthesize(
            query         = query,
            sources       = sources_block,
            system_prompt = _DOCS_SYSTEM,
            model         = ctx.model,
            use_reasoning = ctx.use_reasoning,
            task_label    = "synthesizing docs",
            num_predict   = 1500,
        ):
            yield ev

        yield SkillEvent(kind="citations", content={
            "sources": [{
                "n":       i + 1,
                "title":   p["url"].split("/")[-1] or p["url"],
                "url":     p["url"],
                "snippet": p["content"][:160],
            } for i, p in enumerate(pages[:3])],
        })

        yield SkillEvent(kind="done", content={
            "skill": self.name, "ok": True, "pages_read": len(pages),
        })
