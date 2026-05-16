"""
WebSearchSkill — Level 1 web usage.

Flow:
  1. Detect search intent ("search for X", "find X", "what is X", "latest X", etc.)
  2. Run DuckDuckGo search, fetch top 3 pages in parallel
  3. Feed all pages to the LLM with a prompt that demands:
     - Direct answer to the user's question
     - Inline [1], [2], [3] citations
  4. Stream the answer token-by-token
  5. Emit a structured citations event so the UI can render clickable footer links
"""
from __future__ import annotations
import asyncio, re
from typing import AsyncIterator

from core.skills.base import Skill, SkillContext, SkillEvent
from core.generator    import stream as llm_stream
from core.web_search   import _ddg_search, fetch_page
from core.web_navigator import score_source
from core.skills.web_fetch import _extract_explicit_urls
from core.skills._synthesize import synthesize


# ── Intent detection ────────────────────────────────────────────────────────
# Catches: "search for X", "find latest X", "what is X", "lookup X",
#          "google X", "current X", "google for X", "tell me about X"
_TRIGGER_RE = re.compile(
    r"\b(search\s+(?:for|the\s+web)?|"
    r"find\s+(?:me\s+)?(?:the\s+|info\s+|latest\s+|current\s+|"
                       r"tutorials?\s+|articles?\s+|docs\s+|examples?\s+|"
                       r"resources?\s+|guides?\s+|posts?\s+|news\s+|how)?|"
    r"look\s*up|google|browse|"
    r"latest\s+\w+|current\s+\w+|"
    r"what['']?s\s+the\s+latest|"
    r"news\s+about|article\s+about|tutorial\s+on|tutorial\s+about|"
    r"tutorials?\s+(?:on|about|for)|"
    r"how\s+much\s+does\s+\w+\s+cost|pricing\s+for|prices?\s+(?:of|for))\b",
    re.I,
)

# Soft trigger (only fires when web search is enabled and looks technical/current)
_SOFT_TRIGGER_RE = re.compile(
    r"\b(what['']?s\s+new|recent\s+\w+|202[4-9]|"
    r"this\s+(?:week|month|year)|"
    r"version\s+\d|release\s+notes|changelog)\b",
    re.I,
)


def _matches_intent(query: str) -> bool:
    return bool(_TRIGGER_RE.search(query) or _SOFT_TRIGGER_RE.search(query))


# Skip if query already contains an explicit URL (let WebFetchSkill handle it)
def _has_explicit_url(query: str) -> bool:
    return bool(_extract_explicit_urls(query))


# ── Synthesis prompt ────────────────────────────────────────────────────────
_SYNTHESIZE_SYSTEM = """You are a research assistant. The user asked a question and you have N web sources, each tagged with a quality score (0-100).

Rules for your answer:
1. Answer the user's question DIRECTLY using ONLY the information in the sources.
2. After every factual claim, add an inline citation like [1], [2], or [3] matching
   the source number you got the fact from.
3. PREFER higher-scored sources when sources disagree. If sources conflict on a
   meaningful point, surface it explicitly: "Source [1] says X, but [2] says Y.
   [1] is more authoritative because <reason>" — be honest, not wishy-washy.
4. If the sources don't contain the answer, say "The sources didn't cover this clearly"
   instead of guessing.
5. Be concise — bullet points or short paragraphs. Don't pad.
6. Do NOT list the sources at the end — the UI renders that separately.
"""

_SYNTHESIZE_USER = """User question:
{query}

Web sources (NUMBERED, cite as [N]):
{sources}

Now answer the user using only these sources, with inline [N] citations."""


# ── Skill implementation ────────────────────────────────────────────────────
class WebSearchSkill(Skill):
    name        = "web_search"
    label       = "Web search"
    description = "Search the web, fetch top results, and answer with cited synthesis"
    priority    = 15   # before file_generation (10) — actually wait, file gen is 10 and runs first.
                        # If user says "search for X and make a PDF", file_generation wins. Good.

    def matches(self, ctx: SkillContext) -> bool:
        # Don't fire if the user pasted a URL (let WebFetchSkill handle it)
        if _has_explicit_url(ctx.query):
            return False
        return _matches_intent(ctx.query)

    async def execute(self, ctx: SkillContext) -> AsyncIterator[SkillEvent]:
        query = ctx.query

        # Phase 1 — announce search
        yield SkillEvent(kind="status", content={
            "skill": self.name, "label": self.label,
            "stage": "searching", "query": query,
        })

        # Phase 2 — DuckDuckGo search (sync, fast)
        results = _ddg_search(query, max_results=6)
        if not results or (len(results) == 1 and results[0].get("title") == "Error"):
            yield SkillEvent(kind="answer_chunk",
                              content=f"I couldn't reach DuckDuckGo to search for \"{query}\". "
                                       "Check your network connection or try again.")
            yield SkillEvent(kind="done", content={"skill": self.name, "ok": False, "results": 0})
            return

        # Filter junk URLs
        results = [r for r in results if r.get("url", "").startswith("http")][:4]

        yield SkillEvent(kind="status", content={
            "skill": self.name, "stage": "found_results",
            "count": len(results),
            "results": [{"title": r["title"], "url": r["url"], "snippet": r.get("snippet", "")[:140]} for r in results],
        })

        # Phase 3 — fetch top 3 pages in parallel
        yield SkillEvent(kind="status", content={
            "skill": self.name, "stage": "fetching_pages", "count": min(3, len(results)),
        })
        pages = await asyncio.gather(*[fetch_page(r["url"]) for r in results[:3]])
        fetched = []
        for i, (res, content) in enumerate(zip(results[:3], pages)):
            if content:
                fetched.append({
                    "n":       len(fetched) + 1,
                    "title":   res["title"],
                    "url":     res["url"],
                    "snippet": res.get("snippet", ""),
                    "content": content[:2400],     # cap so we don't blow the model's context
                })

        if not fetched:
            yield SkillEvent(kind="answer_chunk",
                              content=f"Search found results but couldn't fetch readable pages for \"{query}\". "
                                       f"Try opening one of the URLs directly:\n\n" +
                                       "\n".join(f"- {r['title']}: {r['url']}" for r in results[:3]))
            yield SkillEvent(kind="citations", content={"sources": [
                {"n": i + 1, "title": r["title"], "url": r["url"], "snippet": r.get("snippet", "")[:160]}
                for i, r in enumerate(results[:3])
            ]})
            yield SkillEvent(kind="done", content={"skill": self.name, "ok": False, "reason": "no_pages_fetched"})
            return

        # Phase 4 — synthesize answer with citations
        yield SkillEvent(kind="status", content={"skill": self.name, "stage": "synthesizing"})

        # Score every fetched source and sort by quality (highest first)
        for p in fetched:
            p["score"] = score_source(p["url"], p["content"])
        fetched.sort(key=lambda p: -p["score"])
        # Re-number after sorting so citations match priority order
        for i, p in enumerate(fetched):
            p["n"] = i + 1

        sources_block = "\n\n".join(
            f"---\nSource [{p['n']}] (quality {p['score']}/100): {p['title']}\nURL: {p['url']}\n\n{p['content']}"
            for p in fetched
        )
        # Synthesize with the shared helper — honors ctx.use_reasoning
        async for ev in synthesize(
            query         = query,
            sources       = sources_block,
            system_prompt = _SYNTHESIZE_SYSTEM.replace("N", str(len(fetched))),
            model         = ctx.model,
            use_reasoning = ctx.use_reasoning,
            task_label    = "web search synthesis",
            num_predict   = 900,
        ):
            yield ev

        # Phase 5 — emit the citations as a structured event (UI renders a footer)
        yield SkillEvent(kind="citations", content={
            "sources": [
                {"n": p["n"], "title": p["title"], "url": p["url"], "snippet": p["snippet"][:160]}
                for p in fetched
            ],
        })

        yield SkillEvent(kind="done", content={
            "skill": self.name, "ok": True,
            "fetched": len(fetched), "total_results": len(results),
        })
