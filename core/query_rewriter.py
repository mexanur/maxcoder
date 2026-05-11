"""
Query Rewriter — expands vague requests into detailed specifications
before they hit the main model.
Uses the FAST (3B) model to keep latency low.
"""
from __future__ import annotations
from core.generator import generate

REWRITE_SYSTEM = """You are a requirements analyst. Given a vague coding request, output a
detailed specification in this format:

TASK: <one sentence summary>
LANGUAGE/FRAMEWORK: <detected or "not specified">
REQUIREMENTS:
- <bullet 1>
- <bullet 2>
...
CONSTRAINTS: <performance, security, style preferences if any>
CLARIFICATIONS ASSUMED: <list what you assumed>

Be concise. Do NOT write code. Do NOT ask questions.
"""

async def rewrite(query: str, model: str = "maxcoder-fast") -> str:
    """Return an expanded specification string."""
    # Short queries (< 15 words) benefit most from rewriting.
    # Longer detailed queries are passed through mostly unchanged.
    word_count = len(query.split())
    if word_count > 60:
        return query  # already detailed enough

    messages = [
        {"role": "system", "content": REWRITE_SYSTEM},
        {"role": "user", "content": query},
    ]
    try:
        expanded = await generate(messages, model=model)
        return f"{expanded}\n\nOriginal request: {query}"
    except Exception:
        return query  # fallback: use original
