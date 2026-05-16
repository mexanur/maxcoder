"""
WebCompareSkill — Level 1 web usage.

Triggers on comparison intent ("X vs Y", "compare X and Y", "X versus Y").
Searches BOTH items in parallel, fetches top pages for each, then asks the LLM
to produce a markdown comparison table.

Examples:
  "compare FastAPI vs Django"
  "Python vs Rust for systems programming"
  "DigitalOcean vs Linode pricing"
  "compare next.js and remix"
"""
from __future__ import annotations
import asyncio, re
from typing import AsyncIterator

from core.skills.base import Skill, SkillContext, SkillEvent
from core.generator    import stream as llm_stream
from core.web_search   import _ddg_search, fetch_page
from core.skills._synthesize import synthesize


# ── Intent detection ────────────────────────────────────────────────────────
_COMPARE_RE = re.compile(
    r"\b(compare|comparison|"
    r"(\w[\w\-\.\s]{1,40})\s+(?:vs\.?|versus|or|v[/\\])\s+(\w[\w\-\.\s]{1,40})|"
    r"difference\s+between|"
    r"which\s+is\s+(?:better|best|faster|cheaper))\b",
    re.I,
)

# More targeted: "X vs Y" or "compare X and Y"
_EXTRACT_PAIR_RE_VS = re.compile(
    r"\b([\w\-\.\+#]{2,30}(?:\s+[\w\-\.\+#]{1,30})?)\s+(?:vs\.?|versus|v[/\\])\s+"
    r"([\w\-\.\+#]{2,30}(?:\s+[\w\-\.\+#]{1,30})?)\b",
    re.I,
)
_EXTRACT_PAIR_RE_AND = re.compile(
    r"\bcompare\s+([\w\-\.\+#]{2,30}(?:\s+[\w\-\.\+#]{1,30})?)\s+(?:and|with|to)\s+"
    r"([\w\-\.\+#]{2,30}(?:\s+[\w\-\.\+#]{1,30})?)\b",
    re.I,
)


def _extract_pair(query: str) -> tuple[str, str] | None:
    for pat in (_EXTRACT_PAIR_RE_VS, _EXTRACT_PAIR_RE_AND):
        m = pat.search(query)
        if m:
            a, b = m.group(1).strip(), m.group(2).strip()
            # Skip noise pairs like "the and a"
            if len(a) < 2 or len(b) < 2:
                continue
            return a, b
    return None


_COMPARE_SYSTEM = """You are a research assistant. The user wants to compare TWO things, and you have web sources for each.

Output format (markdown):

## Comparison: {A} vs {B}

### TL;DR
One paragraph summary of the key differences.

### Detailed comparison

| Aspect | {A} | {B} |
|--------|-----|-----|
| <criterion 1> | <answer for A>[1] | <answer for B>[2] |
| <criterion 2> | <answer for A>[1] | <answer for B>[2] |
| ... | ... | ... |

### When to choose {A}
- bullet 1[1]
- bullet 2[1]

### When to choose {B}
- bullet 1[2]
- bullet 2[2]

Rules:
- Use ONLY information from the provided sources.
- Cite EVERY claim with [1] (A's sources) or [2] (B's sources) inline.
- Pick aspects that genuinely matter (performance, ease of use, ecosystem, cost, learning curve, etc.).
- If sources don't cover an aspect for one of them, write "(not in sources)" and DO NOT make up data.
"""


_COMPARE_USER = """User asked: {query}

Comparing: **{A}** vs **{B}**

Sources about {A} [cited as [1]]:
{sources_a}

---

Sources about {B} [cited as [2]]:
{sources_b}

Produce the comparison."""


class WebCompareSkill(Skill):
    name        = "web_compare"
    label       = "Web comparison"
    description = "Compares two products/libraries/services using web research with citations"
    priority    = 13   # before web_search (15) — comparison intent should win

    def matches(self, ctx: SkillContext) -> bool:
        return _extract_pair(ctx.query) is not None

    async def execute(self, ctx: SkillContext) -> AsyncIterator[SkillEvent]:
        pair = _extract_pair(ctx.query)
        if not pair:
            return
        item_a, item_b = pair

        yield SkillEvent(kind="status", content={
            "skill": self.name, "label": self.label,
            "stage": "searching_both",
            "a": item_a, "b": item_b,
        })

        # Run two searches in parallel
        loop = asyncio.get_event_loop()
        results_a, results_b = await asyncio.gather(
            loop.run_in_executor(None, _ddg_search, item_a, 3),
            loop.run_in_executor(None, _ddg_search, item_b, 3),
        )
        results_a = [r for r in (results_a or []) if r.get("url", "").startswith("http")][:2]
        results_b = [r for r in (results_b or []) if r.get("url", "").startswith("http")][:2]

        if not results_a or not results_b:
            yield SkillEvent(kind="answer_chunk", content=(
                f"I couldn't find enough sources to compare {item_a} vs {item_b}. "
                f"Try a more specific search."
            ))
            yield SkillEvent(kind="done", content={"skill": self.name, "ok": False})
            return

        yield SkillEvent(kind="status", content={
            "skill": self.name, "stage": "fetching",
            "count": len(results_a) + len(results_b),
        })

        # Fetch top 2 pages of each in parallel
        pages = await asyncio.gather(*[
            *[fetch_page(r["url"]) for r in results_a[:2]],
            *[fetch_page(r["url"]) for r in results_b[:2]],
        ])

        # Split results back into a and b
        pages_a = pages[:len(results_a[:2])]
        pages_b = pages[len(results_a[:2]):]

        fetched_a = [{"title": r["title"], "url": r["url"], "content": c}
                     for r, c in zip(results_a, pages_a) if c]
        fetched_b = [{"title": r["title"], "url": r["url"], "content": c}
                     for r, c in zip(results_b, pages_b) if c]

        if not fetched_a or not fetched_b:
            yield SkillEvent(kind="answer_chunk", content=(
                f"Found search results but couldn't fetch readable content for both "
                f"{item_a} and {item_b}. Try again or use a different phrasing."
            ))
            yield SkillEvent(kind="done", content={"skill": self.name, "ok": False})
            return

        # Build source blocks
        src_a = "\n\n".join(
            f"### Source about {item_a} ({p['title']}):\nURL: {p['url']}\n\n{p['content'][:2200]}"
            for p in fetched_a
        )
        src_b = "\n\n".join(
            f"### Source about {item_b} ({p['title']}):\nURL: {p['url']}\n\n{p['content'][:2200]}"
            for p in fetched_b
        )

        yield SkillEvent(kind="status", content={"skill": self.name, "stage": "synthesizing"})

        combined_sources = (
            f"## Sources about {item_a} (cite as [1]):\n{src_a}\n\n"
            f"## Sources about {item_b} (cite as [2]):\n{src_b}"
        )
        system_prompt = _COMPARE_SYSTEM.replace("{A}", item_a).replace("{B}", item_b)

        async for ev in synthesize(
            query         = ctx.query,
            sources       = combined_sources,
            system_prompt = system_prompt,
            model         = ctx.model,
            use_reasoning = ctx.use_reasoning,
            task_label    = f"comparing {item_a} vs {item_b}",
            num_predict   = 1500,
        ):
            yield ev

        # Citations: [1] = A's sources, [2] = B's sources
        yield SkillEvent(kind="citations", content={
            "sources": [
                {"n": 1, "title": f"[{item_a}] " + p["title"], "url": p["url"], "snippet": p["content"][:160]}
                for p in fetched_a
            ] + [
                {"n": 2, "title": f"[{item_b}] " + p["title"], "url": p["url"], "snippet": p["content"][:160]}
                for p in fetched_b
            ],
        })

        yield SkillEvent(kind="done", content={
            "skill": self.name, "ok": True,
            "a": item_a, "b": item_b,
            "sources_a": len(fetched_a), "sources_b": len(fetched_b),
        })
