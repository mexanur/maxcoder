"""
Response cache — hash-based memoization of (messages, options) → response.

Why this matters on a minimal rig:
  • Identical or near-identical queries happen MORE than people expect:
    - User retries the same question with a typo fix
    - "What can you do?" / "Hi" / "Hello" get asked repeatedly
    - RAG retrieval often produces the same context for similar questions
    - Tool dispatch in the agent retries the same probe
  • Each LLM call burns ~0.5–5 seconds of wall time and 100% of the CPU/GPU.
    A cache hit returns in milliseconds.
  • Disk-backed so it survives server restarts. JSON for portability.

API:
    from core.response_cache import lookup, store

    # In the chat handler, before calling the LLM:
    cached = lookup(messages, options, model)
    if cached:
        return cached

    # After getting a real response:
    response = await generate(messages, model=model, options=options)
    store(messages, options, model, response)

Eviction:
  • TTL — entries expire after CACHE_TTL_SECONDS (default 24h)
  • Size — pruned to MAX_ENTRIES on each store, LRU-style
  • Manual — call clear()

Design tradeoffs:
  • Exact-match only. Two queries differing by one word will NOT hit the
    same entry. That's by design — semantic caching is a separate
    decision-point that needs careful threshold tuning.
  • Streaming responses are cached as their full concatenation; replaying
    a cached entry doesn't stream token-by-token.
"""
from __future__ import annotations
import hashlib, json, os, pathlib, time, threading
from typing import Optional

CACHE_DIR        = pathlib.Path(os.getenv(
    "MAXCODER_CACHE_DIR",
    str(pathlib.Path(__file__).resolve().parent.parent / "data" / "response_cache"),
))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL_SECONDS = int(os.getenv("MAXCODER_CACHE_TTL", str(60 * 60 * 24)))   # 24h
MAX_ENTRIES       = int(os.getenv("MAXCODER_CACHE_MAX", "2000"))
ENABLED           = os.getenv("MAXCODER_CACHE") != "off"

_lock = threading.Lock()
_stats = {"hits": 0, "misses": 0, "stores": 0, "evictions": 0}


def _key(messages: list[dict], options: Optional[dict], model: str) -> str:
    """Stable hash over the inputs that determine the response."""
    canonical = {
        "model":    model,
        "messages": [
            {"role": m.get("role"), "content": m.get("content", "")}
            for m in messages
        ],
        # Only include options that actually affect output
        "options": {
            k: v for k, v in (options or {}).items()
            if k in {"temperature", "top_p", "top_k", "num_predict",
                     "repeat_penalty", "stop", "seed"}
        },
    }
    blob = json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def _path_for(key: str) -> pathlib.Path:
    # Two-level sharding so the cache dir stays sane at scale
    return CACHE_DIR / key[:2] / f"{key}.json"


def lookup(messages: list[dict],
            options: Optional[dict] = None,
            model:   str = "") -> Optional[str]:
    """Return cached response or None. O(1) — just a file read."""
    if not ENABLED:
        return None
    try:
        path = _path_for(_key(messages, options, model))
        if not path.exists():
            with _lock:
                _stats["misses"] += 1
            return None
        with path.open("r", encoding="utf-8") as f:
            entry = json.load(f)
        # TTL check
        if time.time() - entry.get("stored_at", 0) > CACHE_TTL_SECONDS:
            try: path.unlink()
            except Exception: pass
            with _lock:
                _stats["misses"] += 1
            return None
        # Bump access time for LRU eviction
        try:
            os.utime(path, None)
        except Exception:
            pass
        with _lock:
            _stats["hits"] += 1
        return entry.get("response", "")
    except Exception:
        with _lock:
            _stats["misses"] += 1
        return None


def store(messages: list[dict],
           options:  Optional[dict],
           model:    str,
           response: str) -> None:
    """Persist a response. Triggers occasional LRU pruning."""
    if not ENABLED or not response or not response.strip():
        return
    try:
        key  = _key(messages, options, model)
        path = _path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "stored_at": time.time(),
            "model":     model,
            "response":  response,
        }
        with path.open("w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False)
        with _lock:
            _stats["stores"] += 1
        # Every 50 stores, prune if we're over the cap
        if _stats["stores"] % 50 == 0:
            _maybe_prune()
    except Exception:
        pass    # cache failures must never break the request path


def _maybe_prune() -> None:
    """LRU prune to MAX_ENTRIES. Cheap enough to run inline every 50 stores."""
    try:
        files = []
        for p in CACHE_DIR.rglob("*.json"):
            try:
                files.append((p.stat().st_atime, p))
            except Exception:
                continue
        if len(files) <= MAX_ENTRIES:
            return
        files.sort()    # oldest first
        to_evict = len(files) - MAX_ENTRIES
        for _, p in files[:to_evict]:
            try:
                p.unlink()
                with _lock:
                    _stats["evictions"] += 1
            except Exception:
                continue
    except Exception:
        pass


def stats() -> dict:
    """Return current cache stats — useful for debugging hit rates."""
    with _lock:
        s = dict(_stats)
    # Disk-counted entries (might differ from in-process stores after restart)
    try:
        s["entries_on_disk"] = sum(1 for _ in CACHE_DIR.rglob("*.json"))
    except Exception:
        s["entries_on_disk"] = -1
    s["enabled"] = ENABLED
    s["ttl_seconds"] = CACHE_TTL_SECONDS
    s["max_entries"] = MAX_ENTRIES
    total = s["hits"] + s["misses"]
    s["hit_rate"] = round(s["hits"] / total, 3) if total else 0.0
    return s


def clear() -> int:
    """Wipe the cache. Returns number of entries removed."""
    n = 0
    for p in CACHE_DIR.rglob("*.json"):
        try:
            p.unlink()
            n += 1
        except Exception:
            continue
    with _lock:
        _stats.update({"hits": 0, "misses": 0, "stores": 0, "evictions": 0})
    return n
