"""
Model-size auto-router — pick the right model for the query.

Why this matters on a 4GB-VRAM laptop:
  • maxcoder-fast (3B Q4) loads in ~2 GB and runs at ~25 tok/s
  • maxcoder       (7B Q4) loads in ~4 GB and runs at ~9 tok/s
  • Most queries don't need the 7B — greetings, simple facts, file generation
    routing, conversational replies. Routing them to 3B is 2-3× faster and
    keeps VRAM headroom for context.

This is what production LLM serving calls "size-aware routing" — Anthropic
does it (Haiku/Sonnet/Opus picked by complexity), OpenAI does it (gpt-4o-mini
vs gpt-4o), and it's the single biggest throughput win for mixed workloads.

API:
    from core.model_router import pick_model
    model = pick_model(query, history=history, prefer="fast")
    # returns "maxcoder-fast" or "maxcoder"

The router NEVER picks the big model when it's not justified, but always
falls back to it for anything ambiguous — quality bias > speed bias by
default. Set MAXCODER_FORCE_MODEL env var to override entirely.
"""
from __future__ import annotations
import os, re
from typing import Optional

# Public env knobs
_FORCE_MODEL    = os.getenv("MAXCODER_FORCE_MODEL")           # override everything
_FAST_MODEL     = os.getenv("MAXCODER_FAST_MODEL", "maxcoder-fast")
_STRONG_MODEL   = os.getenv("MAXCODER_STRONG_MODEL", "maxcoder")
_ROUTING_OFF    = os.getenv("MAXCODER_ROUTING") == "off"      # disable router

# Queries that almost certainly fit the 3B model.
_FAST_OK_PATTERNS = re.compile(
    r"^\s*("
    r"hi|hello|hey|thanks|thank\s+you|ok|okay|yes|no|sure|"
    r"what\s+can\s+you\s+do|"
    r"what(?:'s|\s+is)\s+(?:the\s+)?(?:date|time|day|year)"
    r")\b",
    re.I,
)

# Strong signals the request needs the 7B coder model. Anything code-heavy,
# long, multi-step, or analytic. False positives are fine here — picking the
# big model when the small one would have worked is a small cost; picking the
# small model when the big one was needed is a quality failure.
_NEEDS_STRONG_PATTERNS = re.compile(
    r"\b("
    # Code & engineering
    r"function|class|method|algorithm|implement|refactor|"
    r"debug|stack\s*trace|exception|traceback|"
    r"compile|runtime|library|framework|"
    r"python|javascript|typescript|rust|go(?:lang)?|java|kotlin|swift|"
    r"c\+\+|csharp|c\#|ruby|php|scala|sql|bash|powershell|"
    r"react|vue|angular|fastapi|django|flask|express|next\.?js|nuxt|"
    r"docker|kubernetes|k8s|aws|gcp|azure|"
    r"\.py|\.js|\.ts|\.jsx|\.tsx|\.rs|\.go|\.java|\.cpp|\.rb|\.php|"
    # Reasoning-heavy verbs
    r"prove|derive|analyse|analyze|evaluate|optimize|optimise|"
    r"compare|contrast|trade.?off|architecture|design|"
    # Multi-step / agentic intent
    r"step.?by.?step|then\s+also|after\s+that|"
    # File generation (needs structured markdown — 7B does it better)
    r"generate\s+(?:a\s+)?(?:pdf|docx|xlsx|csv|excel|word|report)|"
    r"write\s+(?:a\s+)?(?:report|article|essay|document|blog)"
    r")\b",
    re.I,
)


def _query_length_score(query: str) -> int:
    """Rough complexity by length. Very short → fast model is fine."""
    words = len(query.split())
    if words <= 6:
        return 0      # very short
    if words <= 25:
        return 1      # short
    if words <= 80:
        return 2      # medium
    return 3          # long


def pick_model(query:        str,
                history:      Optional[list] = None,
                prefer:       str = "quality",
                use_reasoning: bool = False) -> str:
    """Return the model name to use for this request.

    Args:
      query:         the user's message
      history:       conversation history (currently unused, room for context-aware routing)
      prefer:        "speed" leans toward fast model on ambiguous queries,
                     "quality" (default) leans toward the strong model.
      use_reasoning: if the reasoning toggle is on, always use the strong model.

    Environment overrides (highest priority):
      MAXCODER_FORCE_MODEL=<name>   force every request to use this model
      MAXCODER_ROUTING=off           disable routing entirely (always strong)
    """
    if _FORCE_MODEL:
        return _FORCE_MODEL
    if _ROUTING_OFF or use_reasoning:
        return _STRONG_MODEL

    q = (query or "").strip()
    if not q:
        return _FAST_MODEL

    # 1. Obvious greetings / tiny acknowledgments → fast
    if _FAST_OK_PATTERNS.match(q):
        return _FAST_MODEL

    # 2. Anything code/engineering/reasoning-heavy → strong
    if _NEEDS_STRONG_PATTERNS.search(q):
        return _STRONG_MODEL

    # 3. Length-based fallback
    score = _query_length_score(q)
    if score == 0:
        return _FAST_MODEL
    if score >= 2:
        return _STRONG_MODEL

    # 4. Ambiguous short query — defer to caller's preference
    return _FAST_MODEL if prefer == "speed" else _STRONG_MODEL


def models_in_use() -> dict:
    """Diagnostic — what models the router will hand out."""
    return {
        "fast":          _FAST_MODEL,
        "strong":        _STRONG_MODEL,
        "force":         _FORCE_MODEL or None,
        "routing":       "off" if _ROUTING_OFF else "on",
    }
