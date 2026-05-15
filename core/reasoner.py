"""
MaxThink — custom reasoning pipeline for local LLMs.

Architecture:
  classify(query)  → task_type
  plan(query)      → bullet list of things to check / decide
  think(query)     → <thinking>...</thinking> chain-of-thought
  answer(query)    → final user-facing response
  critic_if_needed → optional review/fix pass

Each stage uses the right model for the job:
  fast model (maxcoder-fast)  → classification, planning
  strong model (maxcoder)     → thinking, answering, critiquing

The full reasoning chain is returned so the UI can show/hide it and
the feedback system can capture it for the RAG flywheel.
"""
from __future__ import annotations
import re, asyncio
from dataclasses import dataclass, field
from typing import Optional, AsyncIterator

from core.generator import generate, stream
from core.prompts   import TEMPLATES


# ── Task classification ──────────────────────────────────────────────────────
# Regex-based fast classifier — no model call needed for obvious cases.
# Falls back to model-based classification for ambiguous queries.

_DEBUG_PAT = re.compile(
    r"\b(debug|fix(\s+this|\s+the|\s+my)?|bug|broken|crash(es|ed|ing)?|error|"
    r"not\s+working|doesn['’]?t\s+work|stuck|fail(s|ed|ing)?|traceback|"
    r"stack\s+trace|why\s+does(n['’]?t)?|why\s+is(n['’]?t)?|throws?|"
    r"undefined|null\s+pointer|exception)\b",
    re.I,
)
_DESIGN_PAT = re.compile(
    r"\b(design|architect(ure)?|how\s+should\s+i\s+structure|tradeoffs?|"
    r"compare|approach(es)?|pattern|microservices?|monolith|database\s+choice|"
    r"choose\s+between|which\s+(library|framework|approach)|build\s+a\s+system)\b",
    re.I,
)
_SQL_PERF_PAT = re.compile(
    r"\b(slow|optimize|performance|query\s+plan|index(es)?|explain|n\+1|"
    r"slow\s+query|database\s+slow|join\s+slow|sql.+slow|tuning)\b",
    re.I,
)
_REFACTOR_PAT = re.compile(
    r"\b(refactor|restructure|extract|deduplicate|clean\s+up|consolidat|"
    r"split\s+into|merge\s+(into|the)|dry|move\s+(this|the|these)\s+to)\b",
    re.I,
)

# Queries that should SKIP reasoning entirely — fast direct answer
_TRIVIAL_PAT = re.compile(
    r"^(hi|hello|hey|thanks|thank you|what can you do|"
    r"generate (a |an )?(pdf|docx|csv|xlsx|txt|excel|word)|"
    r"create (a |an )?(pdf|docx|csv|xlsx|txt|excel|word))",
    re.I,
)

# Code/tech context — if NONE of these words appear, the query is general
# knowledge (science, history, etc.) and we skip the coding-focused reasoning.
_CODE_CONTEXT_PAT = re.compile(
    r"\b(code|coding|function|class|method|variable|loop|array|object|"
    r"string|integer|float|boolean|import|module|package|library|framework|"
    r"api|endpoint|server|backend|frontend|component|hook|state|prop|"
    r"react|vue|angular|svelte|next|nuxt|node|deno|express|fastapi|django|"
    r"flask|rails|spring|laravel|"
    r"python|javascript|typescript|rust|go(lang)?|java|kotlin|swift|"
    r"c\+\+|csharp|c#|ruby|php|scala|haskell|elixir|bash|shell|powershell|"
    r"html|css|sass|tailwind|bootstrap|"
    r"sql|postgres|mysql|sqlite|mongodb|redis|database|query|table|schema|"
    r"docker|kubernetes|k8s|aws|gcp|azure|cloud|"
    r"git|github|gitlab|deploy(ment)?|build|test(s|ing)?|lint|compile|"
    r"bug|error|exception|traceback|stack trace|crash(ed|ing)?|undefined|"
    r"null pointer|segfault|"
    r"useState|useEffect|useMemo|useCallback|useRef|useContext|"
    r"app|application|script|program|algorithm|data structure|"
    r"\.py|\.js|\.ts|\.jsx|\.tsx|\.rs|\.go|\.java|\.c|\.cpp|\.rb|\.php|"
    r"localhost|http|https|json|xml|yaml|html)\b",
    re.I,
)


def classify(query: str) -> str:
    """Return task type. Cheap regex-based for common cases."""
    q = query.strip()
    if _TRIVIAL_PAT.match(q):
        return "trivial"
    # If the query has NO technical context at all, treat as general knowledge
    # → trivial path (no structured reasoning, just answer directly)
    if not _CODE_CONTEXT_PAT.search(q):
        return "trivial"
    # Check most specific patterns first so they beat the general "debug" net
    if _SQL_PERF_PAT.search(q):
        return "sql_perf"
    if _REFACTOR_PAT.search(q):
        return "refactor"
    if _DESIGN_PAT.search(q):
        return "design"
    if _DEBUG_PAT.search(q):
        return "debug"
    return "general"


# ── Reasoning result container ───────────────────────────────────────────────
@dataclass
class ReasoningResult:
    task_type:  str
    plan:       str = ""
    thinking:   str = ""
    answer:     str = ""
    used_models: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task_type":  self.task_type,
            "plan":       self.plan,
            "thinking":   self.thinking,
            "answer":     self.answer,
            "used_models": self.used_models,
        }

    def full_chain_text(self) -> str:
        """Format the full reasoning chain for RAG storage."""
        parts = [f"# Task: {self.task_type}"]
        if self.plan:
            parts.append(f"## Plan\n{self.plan}")
        if self.thinking:
            parts.append(f"## Thinking\n{self.thinking}")
        if self.answer:
            parts.append(f"## Answer\n{self.answer}")
        return "\n\n".join(parts)


# ── Helper: strip <thinking> tags from a model response ─────────────────────
THINKING_RE = re.compile(r"<thinking>([\s\S]*?)</thinking>", re.I)

def extract_thinking(text: str) -> tuple[str, str]:
    """Return (thinking_content, text_without_thinking)."""
    matches = THINKING_RE.findall(text)
    thinking = "\n".join(m.strip() for m in matches).strip()
    cleaned = THINKING_RE.sub("", text).strip()
    return thinking, cleaned


# ── The pipeline ─────────────────────────────────────────────────────────────
# CRITICAL: reasoning stages use BASE qwen models, not maxcoder/maxcoder-fast.
# Reason: Modelfile MESSAGE pairs (few-shot examples about CSV/PDF generation)
# get prepended to every chat with maxcoder, contaminating the reasoning input.
# Base models give clean prompts. The ANSWER stage uses maxcoder where the
# few-shot patterns (@@GENERATE, structured output) are actually useful.
FAST_MODEL    = "qwen2.5-coder:3b"   # 3B base, no few-shot bleed
STRONG_MODEL  = "maxcoder"           # 7B w/ few-shot, used only for final answer
THINK_MODEL   = "qwen2.5-coder:3b"   # 3B base — clean thinking

# Per-stage output caps (tokens). Tuned for the speed/quality sweet-spot on
# a 4GB-VRAM laptop with 3B (think) + 7B (answer) hybrid.
PLAN_OPTS   = {"num_predict":  200, "temperature": 0.2, "num_ctx": 4096}
THINK_OPTS  = {"num_predict":  700, "temperature": 0.4, "num_ctx": 4096}
ANSWER_OPTS = {"num_predict":  800, "temperature": 0.2, "num_ctx": 4096}


async def plan_stage(
    template:    dict,
    query:       str,
    context:     str,
    model:       str = FAST_MODEL,
) -> str:
    msgs = [
        {"role": "system", "content": template["plan_system"]},
        {"role": "user",   "content": template["plan_user"].format(
            query=query, context=context or "(no extra context)",
        )},
    ]
    try:
        return (await generate(msgs, model=model, options=PLAN_OPTS)).strip()
    except Exception as e:
        return f"(planner unavailable: {e})"


async def think_stage_stream(
    template:    dict,
    query:       str,
    plan:        str,
    context:     str,
    model:       str = FAST_MODEL,   # Use 3B for speed (~3x faster than 7B)
) -> AsyncIterator[str]:
    """Stream the thinking stage. Uses fast model by default for speed."""
    msgs = [
        {"role": "system", "content": template["think_system"]},
        {"role": "user",   "content": template["think_user"].format(
            query=query, plan=plan, context=context or "(no extra context)",
        )},
    ]
    async for tok in stream(msgs, model=model, options=THINK_OPTS):
        yield tok


async def think_stage(
    template:    dict,
    query:       str,
    plan:        str,
    context:     str,
    model:       str = FAST_MODEL,
) -> str:
    """Non-streaming wrapper — accumulates streamed tokens then extracts thinking."""
    raw = ""
    async for tok in think_stage_stream(template, query, plan, context, model):
        raw += tok
    thinking, _ = extract_thinking(raw)
    return thinking or raw.strip()


async def answer_stage_stream(
    template:    dict,
    query:       str,
    thinking:    str,
    model:       str = STRONG_MODEL,   # Use 7B for final answer quality
) -> AsyncIterator[str]:
    msgs = [
        {"role": "system", "content": template["answer_system"]},
        {"role": "user",   "content": template["answer_user"].format(
            query=query, thinking=thinking,
        )},
    ]
    async for tok in stream(msgs, model=model, options=ANSWER_OPTS):
        yield tok


async def answer_stage(
    template:    dict,
    query:       str,
    thinking:    str,
    model:       str = STRONG_MODEL,
) -> str:
    msgs = [
        {"role": "system", "content": template["answer_system"]},
        {"role": "user",   "content": template["answer_user"].format(
            query=query, thinking=thinking,
        )},
    ]
    return await generate(msgs, model=model, options=ANSWER_OPTS)


# ── Main entry points ───────────────────────────────────────────────────────
async def reason(
    query:        str,
    context:      str = "",
    task_type:    Optional[str] = None,
    fast_model:   str = FAST_MODEL,
    strong_model: str = STRONG_MODEL,
) -> ReasoningResult:
    """Non-streaming full reasoning pipeline. Returns the complete chain."""
    if task_type is None:
        task_type = classify(query)

    result = ReasoningResult(task_type=task_type)

    if task_type == "trivial":
        # No reasoning needed — direct one-shot
        msgs = [{"role": "user", "content": query}]
        result.answer = await generate(msgs, model=strong_model)
        result.used_models = [strong_model]
        return result

    template = TEMPLATES.get(task_type, TEMPLATES["general"])
    result.used_models = [fast_model, strong_model]

    # Stage 1: plan (cheap, parallel-safe)
    result.plan = await plan_stage(template, query, context, model=fast_model)
    # Stage 2: think (deep)
    result.thinking = await think_stage(template, query, result.plan, context, model=strong_model)
    # Stage 3: answer (final user-facing)
    result.answer = await answer_stage(template, query, result.thinking, model=strong_model)

    return result


async def reason_stream(
    query:        str,
    context:      str = "",
    task_type:    Optional[str] = None,
    fast_model:   str = FAST_MODEL,
    strong_model: str = STRONG_MODEL,
) -> AsyncIterator[dict]:
    """
    Streaming pipeline. Yields events as dicts:
      {"event": "classify",  "task_type": "debug"}
      {"event": "plan",      "content": "..."}
      {"event": "thinking",  "content": "..."}
      {"event": "answer_chunk", "content": "tok"}
      {"event": "done",      "result": {full ReasoningResult.to_dict()}}
    """
    if task_type is None:
        task_type = classify(query)

    yield {"event": "classify", "task_type": task_type}

    result = ReasoningResult(task_type=task_type)

    # Trivial: stream the answer directly
    if task_type == "trivial":
        result.used_models = [strong_model]
        msgs = [{"role": "user", "content": query}]
        full = ""
        async for tok in stream(msgs, model=strong_model):
            full += tok
            yield {"event": "answer_chunk", "content": tok}
        result.answer = full
        yield {"event": "done", "result": result.to_dict()}
        return

    template = TEMPLATES.get(task_type, TEMPLATES["general"])
    result.used_models = [fast_model, strong_model]

    # Stage 1: plan — base 3B model (clean, no Modelfile contamination)
    result.plan = await plan_stage(template, query, context, model=THINK_MODEL)
    yield {"event": "plan", "content": result.plan}

    # Stage 2: think — base 3B model, STREAMED for progress
    yield {"event": "thinking_start"}
    raw_thinking = ""
    async for tok in think_stage_stream(template, query, result.plan, context, model=THINK_MODEL):
        raw_thinking += tok
        yield {"event": "thinking_chunk", "content": tok}
    # Clean up <thinking> tags if model used them
    cleaned, _ = extract_thinking(raw_thinking)
    result.thinking = cleaned or raw_thinking.strip()
    yield {"event": "thinking_done", "content": result.thinking}

    # Stage 3: answer (streamed)
    full = ""
    async for tok in answer_stage_stream(template, query, result.thinking, model=strong_model):
        full += tok
        yield {"event": "answer_chunk", "content": tok}
    result.answer = full

    yield {"event": "done", "result": result.to_dict()}
