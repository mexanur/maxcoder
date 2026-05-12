"""
Context Selector — Phase 3 smart context.

Instead of injecting ALL project files (which blows the 7B context window),
we rank files by semantic similarity to the user query and inject only the
top-k most relevant ones.

Falls back to simple keyword matching if sentence-transformers isn't available.
"""
from __future__ import annotations

import re, pathlib
from core.workspace import WORKSPACE_ROOT, list_files, read_file

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".pdf",
    ".pyc", ".pyd", ".so", ".dll", ".exe",
}

MAX_CHARS_PER_FILE = 2_000
CONTEXT_CAP        = 10_000   # total chars injected


# ── Embedding-based ranking ────────────────────────────────────────────────────
_model = None

def _get_model():
    global _model
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        return _model
    except Exception:
        return None


def _cosine(a, b) -> float:
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)


def _rank_by_embedding(query: str, file_snippets: list[tuple[str, str]]) -> list[tuple[str, str, float]]:
    """Return (path, content, score) sorted by relevance desc."""
    model = _get_model()
    if not model:
        return [(p, c, 0.5) for p, c in file_snippets]  # no model — equal rank

    texts = [query] + [c[:500] for _, c in file_snippets]
    embeddings = model.encode(texts, show_progress_bar=False).tolist()
    q_emb = embeddings[0]
    ranked = []
    for i, (path, content) in enumerate(file_snippets):
        score = _cosine(q_emb, embeddings[i + 1])
        ranked.append((path, content, score))
    return sorted(ranked, key=lambda x: x[2], reverse=True)


# ── Keyword fallback ───────────────────────────────────────────────────────────
def _rank_by_keywords(query: str, file_snippets: list[tuple[str, str]]) -> list[tuple[str, str, float]]:
    """Simple keyword overlap scoring."""
    tokens = set(re.findall(r"\w+", query.lower()))
    ranked = []
    for path, content in file_snippets:
        file_tokens = set(re.findall(r"\w+", (path + " " + content[:500]).lower()))
        score = len(tokens & file_tokens) / (len(tokens) + 1)
        ranked.append((path, content, score))
    return sorted(ranked, key=lambda x: x[2], reverse=True)


# ── Public API ────────────────────────────────────────────────────────────────
def smart_snapshot(project_id: str, query: str, top_k: int = 8) -> str:
    """
    Build a context snapshot injecting only the top_k most relevant files.
    Falls back gracefully if no embeddings model is available.
    """
    all_files = list_files(project_id)
    text_files = [
        f for f in all_files
        if not f["is_dir"]
        and pathlib.Path(f["path"]).suffix.lower() not in BINARY_EXTS
    ]

    if not text_files:
        return ""

    # Read file contents (truncated)
    snippets: list[tuple[str, str]] = []
    for f in text_files:
        content = read_file(project_id, f["path"])
        if content.startswith("ERROR:"):
            continue
        if len(content) > MAX_CHARS_PER_FILE:
            content = content[:MAX_CHARS_PER_FILE] + f"\n... (truncated)"
        snippets.append((f["path"], content))

    if not snippets:
        return ""

    # Rank
    try:
        ranked = _rank_by_embedding(query, snippets)
    except Exception:
        ranked = _rank_by_keywords(query, snippets)

    # Build snapshot up to CONTEXT_CAP
    selected = []
    total    = 0
    for path, content, score in ranked[:top_k]:
        section = f"=== {path} (relevance: {score:.2f}) ===\n{content}"
        if total + len(section) > CONTEXT_CAP:
            break
        selected.append(section)
        total += len(section)

    if not selected:
        return ""

    total_files = len(text_files)
    shown_files = len(selected)
    header = (
        f"RELEVANT PROJECT FILES ({shown_files}/{total_files} shown, "
        f"selected by semantic similarity to your request):\n\n"
    )
    return header + "\n\n".join(selected)
