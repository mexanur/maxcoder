"""
Conversation Feedback — capture thumbs-up / thumbs-down on assistant responses.

The flywheel:
  - User clicks 👍 → response saved to JSONL log AND added to the RAG `snippets`
    index, so future similar queries will retrieve it as expert context.
  - User clicks 👎 → response saved only to JSONL log (with optional reason)
    for later review / analysis. Not injected into prompts.

Storage:
  feedback_store/positive.jsonl   — approved Q/A pairs
  feedback_store/negative.jsonl   — rejected responses
  rag/indexes/snippets/           — vector store of approved exchanges
"""
from __future__ import annotations
import json, uuid, datetime, pathlib
from typing import Optional

from core.rag_retriever import index_texts

FEEDBACK_DIR = pathlib.Path(__file__).parent.parent / "feedback_store"
FEEDBACK_DIR.mkdir(exist_ok=True)

POS_LOG = FEEDBACK_DIR / "positive.jsonl"
NEG_LOG = FEEDBACK_DIR / "negative.jsonl"


def _append_jsonl(path: pathlib.Path, entry: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _read_jsonl(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _format_for_rag(query: str, response: str) -> str:
    """Combine a Q/A pair into a single document for semantic indexing."""
    return (
        f"# Approved exchange\n\n"
        f"## User asked\n{query.strip()}\n\n"
        f"## Expert response\n{response.strip()}\n"
    )


def save_positive(
    query:    str,
    response: str,
    model:    str = "",
    files:    Optional[list[dict]] = None,
) -> dict:
    """Persist a thumbs-up exchange and index it for future retrieval."""
    fid = str(uuid.uuid4())
    entry = {
        "id":       fid,
        "kind":     "positive",
        "query":    query,
        "response": response,
        "model":    model,
        "files":    files or [],
        "ts":       datetime.datetime.utcnow().isoformat(),
    }
    _append_jsonl(POS_LOG, entry)

    # Add to RAG snippets index so future similar queries retrieve this
    try:
        rag_doc = _format_for_rag(query, response)
        added = index_texts(
            texts=[rag_doc],
            index_name="snippets",
            metadatas=[{
                "source":      "feedback",
                "feedback_id": fid,
                "model":       model,
                "ts":          entry["ts"],
            }],
        )
        entry["indexed"] = added > 0
        if not added:
            entry["index_error"] = "index_texts returned 0 — chromadb may be unavailable"
    except Exception as e:
        entry["indexed"] = False
        entry["index_error"] = str(e)

    return entry


def save_negative(
    query:    str,
    response: str,
    reason:   str = "",
    model:    str = "",
) -> dict:
    """Persist a thumbs-down exchange (NOT indexed for retrieval)."""
    fid = str(uuid.uuid4())
    entry = {
        "id":       fid,
        "kind":     "negative",
        "query":    query,
        "response": response,
        "reason":   reason,
        "model":    model,
        "ts":       datetime.datetime.utcnow().isoformat(),
    }
    _append_jsonl(NEG_LOG, entry)
    return entry


def list_feedback(kind: str = "all", limit: int = 50) -> list[dict]:
    """List recent feedback entries. kind: 'positive' | 'negative' | 'all'."""
    out: list[dict] = []
    if kind in ("positive", "all"):
        out.extend(_read_jsonl(POS_LOG))
    if kind in ("negative", "all"):
        out.extend(_read_jsonl(NEG_LOG))
    out.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return out[:limit]


def delete_feedback(fid: str) -> bool:
    """Remove a feedback entry by id from BOTH log files."""
    removed = False
    for path in (POS_LOG, NEG_LOG):
        if not path.exists():
            continue
        keep: list[dict] = []
        for e in _read_jsonl(path):
            if e.get("id") == fid:
                removed = True
                continue
            keep.append(e)
        path.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in keep) + ("\n" if keep else ""),
            encoding="utf-8",
        )
    return removed


def stats() -> dict:
    """Counts and most recent timestamps."""
    pos = _read_jsonl(POS_LOG)
    neg = _read_jsonl(NEG_LOG)
    return {
        "positive": len(pos),
        "negative": len(neg),
        "total":    len(pos) + len(neg),
        "last_positive": pos[-1]["ts"] if pos else None,
        "last_negative": neg[-1]["ts"] if neg else None,
    }
