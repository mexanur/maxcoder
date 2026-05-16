"""
Shared synthesis helper — every skill calls this for its "give me the answer"
step. Honors the user's thinking toggle so reasoning improves ALL outputs,
not just plain chat.

Two paths:
  use_reasoning=False (fast):    one LLM stream, ~10-30s
  use_reasoning=True  (deep):    plan → think → answer pipeline, ~60-150s
                                   - Plan step asks: "what aspects matter most?"
                                   - Think step walks through every source critically
                                   - Answer step writes the final response with citations

Events emitted (forwarded to UI by the skill's run_skill loop):
  status   → task_thinking_delta / task_thinking_done   (live thinking preview)
  status   → task_content_delta                          (live content preview)
  status   → task_complete                               (clear the live preview)
  answer_chunk → final @@GENERATE-free answer text       (user-visible)
"""
from __future__ import annotations
from typing import AsyncIterator, Optional

from core.skills.base import SkillEvent
from core.generator    import generate, stream as llm_stream


# ── Plan step prompt — used when reasoning is on ────────────────────────────
_PLAN_SYSTEM = """You are a planning assistant. Output a short, focused plan
(3-5 bullets) for how to answer the user's question using the given sources.
Just the plan. No answer yet. Be concrete: which sources matter most, which
aspects to cover, what to watch for (conflicts, gaps, key data)."""

_PLAN_USER = """User's question:
{query}

Available sources (numbered, with quality scores when present):
{sources_preview}

Output a 3-5 bullet plan for how to answer."""


# ── Think step prompt — walks through sources critically ───────────────────
_THINK_SYSTEM = """Use <thinking>...</thinking> to reason BEFORE answering.

Inside <thinking>, for each source:
- What does it claim? Which claims are most relevant to the user's question?
- How does its quality / authority affect its weight?
- Where do sources agree? Where do they disagree?
- What's the safest synthesis given the evidence?

Be specific. Reference source numbers [1], [2], etc. Don't write the final
answer here — that comes next. Keep total thinking under 700 chars."""

_THINK_USER = """Plan you produced:
{plan}

Now do the deep reasoning inside <thinking>...</thinking>.

User's question:
{query}

Sources:
{sources}"""


# ── Answer step uses the skill's own system prompt ─────────────────────────
_ANSWER_USER = """Your plan:
{plan}

Your reasoning:
{thinking}

Now write the final answer using ONLY the provided sources.

User's question:
{query}

Sources:
{sources}"""


async def synthesize(
    *,
    query:          str,
    sources:        str,
    system_prompt:  str,          # the skill's own "answer like this" instructions
    model:          str,
    use_reasoning:  bool,
    task_label:     str   = "synthesis",
    task_index:     int   = 0,
    num_predict:    int   = 1200,
    num_ctx:        int   = 8192,
) -> AsyncIterator[SkillEvent]:
    """Stream synthesis events. Honors the user's reasoning toggle.

    On fast path: one llm_stream call, content tokens go directly to UI.
    On reasoning path: plan → think → answer, with live thinking preview.
    """
    options = {"num_predict": num_predict, "temperature": 0.2, "num_ctx": num_ctx}

    # ───────── FAST PATH ─────────
    if not use_reasoning:
        msgs = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": (
                f"User's question:\n{query}\n\n"
                f"Sources:\n{sources}\n\n"
                f"Now answer."
            )},
        ]
        async for tok in llm_stream(msgs, model=model, options=options):
            yield SkillEvent(kind="answer_chunk", content=tok)
        return

    # ───────── REASONING PATH ─────────
    # Stage 1: PLAN
    yield SkillEvent(kind="status", content={
        "stage": "generating", "index": task_index, "total": 1,
        "title": task_label, "complex": True, "fmt": "",
    })

    sources_preview = sources[:1500] + ("…" if len(sources) > 1500 else "")
    plan_msgs = [
        {"role": "system", "content": _PLAN_SYSTEM},
        {"role": "user",   "content": _PLAN_USER.format(
            query=query, sources_preview=sources_preview,
        )},
    ]
    try:
        plan = (await generate(
            plan_msgs, model=model,
            options={"num_predict": 250, "temperature": 0.2, "num_ctx": 4096},
        )).strip()
    except Exception:
        plan = "(planner unavailable — proceeding with direct synthesis)"

    yield SkillEvent(kind="status", content={
        "stage": "task_plan", "index": task_index,
        "title": task_label, "plan": plan,
    })

    # Stage 2: THINK — STREAMED so the user sees it building up
    think_msgs = [
        {"role": "system", "content": _THINK_SYSTEM},
        {"role": "user",   "content": _THINK_USER.format(
            plan=plan, query=query, sources=sources,
        )},
    ]
    raw_thinking = ""
    async for tok in llm_stream(
        think_msgs, model=model,
        options={"num_predict": 700, "temperature": 0.3, "num_ctx": num_ctx},
    ):
        raw_thinking += tok
        yield SkillEvent(kind="status", content={
            "stage": "task_thinking_delta", "index": task_index,
            "title": task_label, "delta": tok,
        })

    # Strip the <thinking> tags if model used them
    import re
    cleaned = re.sub(r'</?thinking>', '', raw_thinking).strip()
    yield SkillEvent(kind="status", content={
        "stage": "task_thinking_done", "index": task_index,
        "title": task_label, "thinking": cleaned,
    })

    # Stage 3: ANSWER — streamed to the user as the visible response
    answer_msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": _ANSWER_USER.format(
            plan=plan, thinking=cleaned, query=query, sources=sources,
        )},
    ]
    async for tok in llm_stream(answer_msgs, model=model, options=options):
        yield SkillEvent(kind="answer_chunk", content=tok)

    # Mark the live preview complete so UI swaps to the final state
    yield SkillEvent(kind="status", content={
        "stage": "task_complete", "index": task_index,
        "title": task_label,
    })
