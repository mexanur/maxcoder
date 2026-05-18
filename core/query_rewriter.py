"""
Query Rewriter — expands VAGUE CODING requests into detailed specifications
before they hit the main model.

CRITICAL: only rewrites genuine coding/technical requests. Conversational
questions ("who are you?", "tell me a joke"), greetings, general knowledge,
and trivial queries are passed through unchanged — running them through the
requirements-analyst prompt was producing absurd output like "Requirements
Analysis Task Specification" for "who are you?".

Uses the FAST (3B) model to keep latency low.
"""
from __future__ import annotations
import re
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


# Patterns that indicate the query is a coding-related request that would
# actually benefit from expansion into a spec.
_CODING_REQUEST_PAT = re.compile(
    r"\b("
    # Direct code verbs
    r"write|create|build|generate|implement|refactor|fix|debug|optimize|"
    r"add|remove|change|modify|update|extend|migrate|port|convert|"
    # Code/tech nouns
    r"function|class|method|module|component|endpoint|api|"
    r"feature|bug|error|exception|test|tests|"
    # Languages / stacks
    r"python|javascript|typescript|rust|go(?:lang)?|java|kotlin|swift|"
    r"react|vue|angular|fastapi|django|flask|node|express|next\.?js|"
    r"sql|database|query|schema|migration|"
    # Project verbs
    r"deploy|setup|configure|install|integrate|"
    r"\.py|\.js|\.ts|\.jsx|\.tsx|\.rs|\.go|\.java"
    r")\b",
    re.I,
)

# Patterns that indicate the query is conversational / non-technical and
# should NEVER be rewritten.
_NON_CODE_PAT = re.compile(
    r"^\s*("
    r"hi|hello|hey|thanks|thank\s+you|ok|okay|yes|no|sure|"
    r"who\s+(?:are|is)|what(?:'s|\s+is|\s+can)\s+you|what\s+are\s+you|"
    r"tell\s+me|describe|explain|why|how\s+come|"
    r"do\s+you|can\s+you|are\s+you|will\s+you|"
    r"what\s+(?:is|are|was|were)\s+(?:the|a|an)|"
    r"joke|fact|story|opinion|advice"
    r")\b",
    re.I,
)


def _is_coding_request(query: str) -> bool:
    """True if the query should go through the requirements-analyst rewrite."""
    if not query or not query.strip():
        return False
    q = query.strip()
    # Pure conversational signals — never rewrite
    if _NON_CODE_PAT.match(q):
        return False
    # Must have an explicit coding signal to rewrite
    return bool(_CODING_REQUEST_PAT.search(q))


async def rewrite(query: str, model: str = "maxcoder-fast") -> str:
    """Return an expanded specification string, or the original query
    unchanged if rewriting isn't appropriate.

    Only rewrites short, genuinely vague CODING requests. Conversational
    queries, greetings, and general questions are passed through.
    """
    if not _is_coding_request(query):
        return query

    # Long detailed coding queries don't need expansion either
    word_count = len(query.split())
    if word_count > 60:
        return query

    messages = [
        {"role": "system", "content": REWRITE_SYSTEM},
        {"role": "user", "content": query},
    ]
    try:
        expanded = await generate(messages, model=model)
        return f"{expanded}\n\nOriginal request: {query}"
    except Exception:
        return query   # fallback: use original
