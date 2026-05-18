"""
Multi-index RAG retriever.
Indexes:
  - language_docs   : official language / framework documentation
  - codebase        : your own project files
  - error_solutions : known errors + fixes
  - snippets        : curated high-quality code examples
"""
from __future__ import annotations
import os, pathlib

# Silence ChromaDB telemetry (see core/memory.py for context).
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "True")

INDEX_DIR = pathlib.Path(__file__).parent.parent / "rag" / "indexes"
INDEX_DIR.mkdir(parents=True, exist_ok=True)

INDEXES = ["language_docs", "codebase", "error_solutions", "snippets"]

_cols: dict = {}

def _get_col(name: str):
    if name in _cols:
        return _cols[name]
    db_path = INDEX_DIR / name
    if not db_path.exists():
        _cols[name] = None
        return None
    try:
        import chromadb
        from chromadb.utils import embedding_functions
        client = chromadb.PersistentClient(path=str(db_path))
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2")
        _cols[name] = client.get_or_create_collection(name, embedding_function=ef)
    except Exception as e:
        print(f"[rag] index {name} disabled: {e}")
        _cols[name] = None
    return _cols[name]


def retrieve(query: str, k_per_index: int = 3) -> str:
    """Query all available indexes and return combined context."""
    results = []
    for idx in INDEXES:
        col = _get_col(idx)
        if not col:
            continue
        try:
            count = col.count()
            if count == 0:
                continue
            k = min(k_per_index, count)
            r = col.query(query_texts=[query], n_results=k)
            docs = r.get("documents", [[]])[0]
            if docs:
                results.append(f"=== {idx.upper()} ===\n" + "\n---\n".join(docs))
        except Exception:
            continue
    if not results:
        return ""
    return "RETRIEVED REFERENCE DOCS:\n\n" + "\n\n".join(results)


def index_texts(texts: list[str], index_name: str,
                metadatas: list[dict] | None = None) -> int:
    """Add texts to a named index. Returns count added."""
    import uuid
    db_path = INDEX_DIR / index_name
    db_path.mkdir(parents=True, exist_ok=True)
    try:
        import chromadb
        from chromadb.utils import embedding_functions
        client = chromadb.PersistentClient(path=str(db_path))
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2")
        col = client.get_or_create_collection(index_name, embedding_function=ef)
        metas = metadatas or [{}] * len(texts)
        col.add(documents=texts,
                ids=[str(uuid.uuid4()) for _ in texts],
                metadatas=metas)
        _cols.pop(index_name, None)  # reset cached handle
        return len(texts)
    except Exception as e:
        print(f"[rag] index_texts error: {e}")
        return 0
