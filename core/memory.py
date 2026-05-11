"""
Long-term memory store using ChromaDB.
Remembers user preferences, tech stack choices, and past decisions.
Auto-injects relevant memories into every prompt.
"""
from __future__ import annotations
import pathlib, uuid, datetime

MEMORY_DIR = pathlib.Path(__file__).parent.parent / "memory_store"
MEMORY_DIR.mkdir(exist_ok=True)

_col = None

def _get_col():
    global _col
    if _col is not None:
        return _col
    try:
        import chromadb
        from chromadb.utils import embedding_functions
        client = chromadb.PersistentClient(path=str(MEMORY_DIR))
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2")
        _col = client.get_or_create_collection("memories", embedding_function=ef)
    except Exception as e:
        print(f"[memory] disabled: {e}")
        _col = None
    return _col


def save(text: str, category: str = "general") -> None:
    """Save a memory fact."""
    col = _get_col()
    if not col:
        return
    col.add(
        documents=[text],
        ids=[str(uuid.uuid4())],
        metadatas=[{"category": category,
                    "ts": datetime.datetime.utcnow().isoformat()}],
    )


def retrieve(query: str, k: int = 5) -> str:
    """Return relevant memories as a formatted string."""
    col = _get_col()
    if not col:
        return ""
    try:
        count = col.count()
        if count == 0:
            return ""
        k = min(k, count)
        r = col.query(query_texts=[query], n_results=k)
        docs = r.get("documents", [[]])[0]
        if not docs:
            return ""
        return "USER PREFERENCES & MEMORY:\n" + "\n".join(f"- {d}" for d in docs)
    except Exception:
        return ""


def list_all() -> list[str]:
    """Return all stored memories."""
    col = _get_col()
    if not col:
        return []
    try:
        r = col.get()
        return r.get("documents", [])
    except Exception:
        return []


def delete_all() -> None:
    """Wipe all memories."""
    col = _get_col()
    if not col:
        return
    try:
        all_ids = col.get()["ids"]
        if all_ids:
            col.delete(ids=all_ids)
    except Exception:
        pass
