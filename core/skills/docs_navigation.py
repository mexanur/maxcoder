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
from core.web_navigator import crawl, score_source
from core.skills._synthesize import synthesize


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
    r"react|vue|angular|svelte|next(?:js)?|nuxt|remix|"
    r"pydantic|sqlalchemy|prisma|drizzle|tanstack|"
    r"tailwind(?:css)?|chakra|bootstrap|"
    r"docker|kubernetes|k8s|terraform|ansible|"
    r"aws|gcp|azure|cloudflare|vercel|netlify|"
    r"python|javascript|typescript|rust|golang|go|java|kotlin|swift|"
    r"postgres|mysql|sqlite|mongodb|redis|"
    r"pytorch|tensorflow|huggingface|langchain|llama|ollama|anthropic|openai)\b",
    re.I,
)


_DOCS_SYSTEM = """You are a technical documentation assistant. You have fetched MULTIPLE documentation pages on the user's topic.

Rules:
1. Answer the user's question by combining ALL sources.
2. Use inline [1], [2], [3]... citations matching the source numbers below.
3. Show concrete code examples when the docs have them — fenced with ```lang.
4. If sources contradict each other (e.g. old vs new API), note both and prefer the most recent / authoritative.
5. If a page covers a sub-topic the user might want next, mention it briefly.
6. Output format: short intro → code snippet → bullet explanation → gotchas if any.
7. Use ONLY information from the provided sources. NEVER invent API methods or signatures.
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

        # Phase 1: search for the right docs page
        yield SkillEvent(kind="status", content={
            "skill": self.name, "label": self.label,
            "stage": "searching", "query": query,
        })

        # Build a docs-focused search query
        search_query = query
        # Prepend "site:" hints for major frameworks to bias toward official docs
        framework_match = _FRAMEWORK_RE.search(query)
        site_hint = ""
        if framework_match:
            fw = framework_match.group(0).lower()
            site_hint_map = {
                "fastapi": "site:fastapi.tiangolo.com",
                "pydantic": "site:docs.pydantic.dev",
                "react": "site:react.dev",
                "next": "site:nextjs.org", "nextjs": "site:nextjs.org",
                "rust": "site:doc.rust-lang.org",
                "python": "site:docs.python.org",
                "django": "site:djangoproject.com",
            }
            site_hint = site_hint_map.get(fw, "")

        results = _ddg_search(f"{site_hint} {query}".strip(), max_results=4)
        results = [r for r in results if r.get("url", "").startswith("http")][:3]
        if not results:
            yield SkillEvent(kind="answer_chunk",
                              content="Couldn't find documentation pages for that query. "
                                       "Try rephrasing or naming the framework explicitly.")
            yield SkillEvent(kind="done", content={"skill": self.name, "ok": False})
            return

        # Pick the highest-authority result as the docs root
        root_url = max(results, key=lambda r: score_source(r["url"]))["url"]

        yield SkillEvent(kind="status", content={
            "skill": self.name, "stage": "crawling",
            "root": root_url, "max_pages": 3,
        })

        # Phase 2: crawl root + up to 2 sub-links matching the topic
        topic_kws = [w for w in re.findall(r'\b[a-zA-Z]{4,}\b', query)
                     if w.lower() not in {'how', 'what', 'why', 'show', 'docs',
                                          'documentation', 'tutorial', 'guide',
                                          'reference', 'about', 'find'}][:6]

        pages = []
        async def _on_progress(ev):
            pass
        try:
            pages = await crawl(root_url, topic_keywords=topic_kws, max_pages=3,
                                on_progress=_on_progress)
        except Exception as e:
            yield SkillEvent(kind="answer_chunk",
                              content=f"Couldn't crawl docs: {e}")
            yield SkillEvent(kind="done", content={"skill": self.name, "ok": False})
            return

        if not pages:
            yield SkillEvent(kind="answer_chunk",
                              content=f"Couldn't read the docs root page at {root_url}.")
            yield SkillEvent(kind="done", content={"skill": self.name, "ok": False})
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
