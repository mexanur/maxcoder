"""
LLM backend — direct llama-cpp-python bindings (no Ollama daemon).

Why direct llama-cpp:
  • Same inference engine Ollama uses underneath — zero quality difference
  • No HTTP serialization, no daemon process, no IPC overhead
  • Unlocks features Ollama hides: speculative decoding, prompt caching,
    fine-grained KV cache control, logit access
  • Runs IN our Python process — simpler deployment, one less service

Memory model on a 4GB-VRAM laptop:
  • Only ONE model fits in VRAM at a time (3B Q4 = ~2GB, 7B Q4 = ~3.8GB)
  • ModelManager lazy-loads on first use, swaps when a different model is
    requested. Swap cost is ~3-5s (model load), then steady state.
  • Idle VRAM after swap-out is reclaimed by closing the Llama instance.

Public API (drop-in compatible with the old Ollama wrapper):
  generate(messages, model=..., options=..., use_cache=True) -> str
  stream(messages, model=..., options=..., use_cache=True)   -> async iter[str]

Configuration via env (sensible defaults — most users need nothing):
  MAXCODER_MODEL_FAST_PATH    path to 3B Q4 GGUF
  MAXCODER_MODEL_STRONG_PATH  path to 7B Q4 GGUF
  MAXCODER_GPU_LAYERS_FAST    GPU layers for 3B (default 99 = all)
  MAXCODER_GPU_LAYERS_STRONG  GPU layers for 7B (default 24 = partial CPU offload)
  MAXCODER_N_CTX              context window size (default 4096)
  MAXCODER_KV_CACHE_TYPE      'fp16' (default) or 'q8_0' or 'q4_0' (smaller)
"""
from __future__ import annotations
import asyncio, os, threading, time
from pathlib import Path
from typing import AsyncIterator, Optional

from llama_cpp import Llama

from core.response_cache import lookup as _cache_lookup, store as _cache_store


# ── Configuration ───────────────────────────────────────────────────────────
# Default model paths point at Ollama's blob store so users don't need to
# duplicate the GGUF files. Override via env vars if you've moved them.
_DEFAULT_FAST_PATH   = (
    r"C:\Users\mnuri\.ollama\models\blobs"
    r"\sha256-4a188102020e9c9530b687fd6400f775c45e90a0d7baafe65bd0a36963fbb7ba"
)
_DEFAULT_STRONG_PATH = (
    r"C:\Users\mnuri\.ollama\models\blobs"
    r"\sha256-60e05f2100071479f596b964f89f510f057ce397ea22f2833a0cfe029bfc2463"
)

MODEL_PATHS = {
    "maxcoder-fast": os.getenv("MAXCODER_MODEL_FAST_PATH",   _DEFAULT_FAST_PATH),
    "maxcoder":      os.getenv("MAXCODER_MODEL_STRONG_PATH", _DEFAULT_STRONG_PATH),
}
# Tolerate user-passed "maxcoder-fast:latest" / "maxcoder:latest" by stripping tag
_TAG_ALIASES = {f"{k}:latest": k for k in MODEL_PATHS}

GPU_LAYERS = {
    "maxcoder-fast": int(os.getenv("MAXCODER_GPU_LAYERS_FAST",   "99")),
    "maxcoder":      int(os.getenv("MAXCODER_GPU_LAYERS_STRONG", "24")),
}
N_CTX           = int(os.getenv("MAXCODER_N_CTX",          "16384"))   # 16k — 4× the old default
KV_CACHE_TYPE   =     os.getenv("MAXCODER_KV_CACHE_TYPE",  "q8_0")    # Q8 KV — halves cache VRAM at ~0% quality loss

# Map human-readable KV cache types to ggml integer constants llama-cpp expects.
# Values from ggml.h: F16=1, Q4_0=2, Q5_0=6, Q8_0=8.
_GGML_TYPES = {"fp16": 1, "f16": 1, "q4_0": 2, "q5_0": 6, "q8_0": 8}

# ── Speculative decoding ────────────────────────────────────────────────────
# Modes:
#   "off"           — no speculation, plain decoding (DEFAULT)
#   "prompt_lookup" — n-gram lookup in the prompt itself (mathematically
#                     equivalent output, ~1.3-1.5× faster)
#   "draft_model"   — use the 3B as a draft for the 7B (~1.5-2.5× faster but
#                     uses ~1.5 GB extra memory)
#
# ⚠️ KNOWN ISSUE: speculative decoding is BROKEN in llama-cpp-python 0.3.4
# (the latest version with a prebuilt CUDA 12.1 wheel for Python 3.11). Both
# modes crash with internal buffer-shape mismatches at long contexts.
# Tracking: github.com/abetlen/llama-cpp-python issues.
#
# To enable: either compile llama-cpp-python from source (needs CUDA Toolkit +
# VS Build Tools), or wait for a newer prebuilt wheel.
SPECULATIVE_MODE        =     os.getenv("MAXCODER_SPECULATIVE_MODE",   "off")
SPECULATIVE_PRED_TOKENS = int(os.getenv("MAXCODER_SPECULATIVE_TOKENS", "5"))
SPECULATIVE_NGRAM       = int(os.getenv("MAXCODER_SPECULATIVE_NGRAM",  "2"))

# ── Prefix cache ────────────────────────────────────────────────────────────
# When the same prompt PREFIX appears across requests (same system prompt,
# same RAG context, same conversation history), we can skip re-evaluating
# those tokens entirely. llama-cpp keeps the KV-cache state keyed by the
# token sequence; a matching prefix reuses the saved state.
#
# Modes:
#   "ram"  — keep state in RAM (default). Fastest cache hits. Lost on restart.
#   "disk" — persist to disk. Slightly slower hits but survives restarts.
#   "off"  — no cache (don't enable unless you suspect cache bugs)
#
# Size: default 2 GB cap. The cache evicts oldest entries when full. On a
# 16 GB RAM laptop, 2 GB is comfortable headroom.
PREFIX_CACHE_MODE  =     os.getenv("MAXCODER_PREFIX_CACHE",      "ram")
PREFIX_CACHE_BYTES = int(os.getenv("MAXCODER_PREFIX_CACHE_BYTES", str(2 * 1024 * 1024 * 1024)))
PREFIX_CACHE_DIR   =     os.getenv("MAXCODER_PREFIX_CACHE_DIR",  ".cache/llama_prefix")
DEFAULT_MODEL   =     os.getenv("MAXCODER_MODEL",          "maxcoder-fast")


def _resolve_name(name: Optional[str]) -> str:
    """Normalize 'maxcoder:latest' → 'maxcoder' and apply default."""
    if not name:
        return DEFAULT_MODEL
    return _TAG_ALIASES.get(name, name)


# ── ModelManager: lazy load + swap (one model in VRAM at a time) ────────────
def _make_speculator(main_name: str):
    """Construct the draft-token generator to pass into Llama.

    Returns either:
      • LlamaPromptLookupDecoding instance — n-gram lookup, no extra model
      • Llama instance loaded with the draft model
      • None — speculation disabled
    """
    mode = SPECULATIVE_MODE.lower()
    if mode in ("off", "none", ""):
        return None

    if mode == "prompt_lookup":
        try:
            from llama_cpp.llama_speculative import LlamaPromptLookupDecoding
            return LlamaPromptLookupDecoding(
                max_ngram_size  = SPECULATIVE_NGRAM,
                num_pred_tokens = SPECULATIVE_PRED_TOKENS,
            )
        except Exception as e:
            import sys
            print(f"[llm_backend] prompt_lookup setup failed: {e} — falling back to off",
                  file=sys.stderr, flush=True)
            return None

    if mode == "draft_model":
        # Use the OTHER model as the draft. If main is `maxcoder` (7B) the
        # draft is `maxcoder-fast` (3B), and vice versa. The two MUST share
        # tokenizer vocab — Qwen2.5-Coder 3B and 7B do, so this is safe.
        draft_name = "maxcoder-fast" if main_name == "maxcoder" else "maxcoder"
        draft_path = MODEL_PATHS.get(draft_name)
        if not draft_path or not Path(draft_path).exists():
            import sys
            print(f"[llm_backend] draft model {draft_name!r} not found — speculation disabled",
                  file=sys.stderr, flush=True)
            return None
        try:
            # The draft is CPU-only by default to leave VRAM for the main model.
            # Override via MAXCODER_DRAFT_GPU_LAYERS if you've reduced the main
            # model's GPU layers to free VRAM for a GPU-resident draft.
            draft_gpu = int(os.getenv("MAXCODER_DRAFT_GPU_LAYERS", "0"))
            draft = Llama(
                model_path   = draft_path,
                n_gpu_layers = draft_gpu,
                n_ctx        = N_CTX,
                verbose      = False,
            )
            return draft
        except Exception as e:
            import sys
            print(f"[llm_backend] draft model load failed: {e} — speculation disabled",
                  file=sys.stderr, flush=True)
            return None

    return None


class _ModelManager:
    """Single-slot model cache. The 4GB-VRAM constraint means we keep at most
    ONE Llama instance alive — swapping costs ~3-5s but avoids OOM."""
    _instance:           Optional[Llama] = None
    _instance_name:      str             = ""
    _draft:              Optional[object]= None    # speculative-decoding helper
    _draft_kind:         str             = ""
    _prefix_cache_kind:  str             = "off"   # ram | disk | off
    _lock:               threading.Lock  = threading.Lock()

    @classmethod
    def get(cls, name: str) -> Llama:
        name = _resolve_name(name)
        if cls._instance is not None and cls._instance_name == name:
            return cls._instance

        with cls._lock:
            # Re-check inside the lock — another thread may have loaded it
            if cls._instance is not None and cls._instance_name == name:
                return cls._instance

            # Unload previous model + draft to free VRAM
            cls._unload_unlocked()

            path = MODEL_PATHS.get(name)
            if not path or not Path(path).exists():
                raise FileNotFoundError(
                    f"Model {name!r} not found. Expected GGUF at: {path!r}\n"
                    f"Configure via MAXCODER_MODEL_{'FAST' if 'fast' in name else 'STRONG'}_PATH env var."
                )

            t0 = time.time()

            # Build the speculator BEFORE the main model so we know if it's
            # a draft Llama (uses VRAM) or just an n-gram lookup (free).
            draft = _make_speculator(name)
            draft_kind = ""
            if draft is not None:
                draft_kind = type(draft).__name__

            # Compatibility matrix on llama-cpp-python 0.3.4:
            #   • flash_attn=True + LlamaPromptLookupDecoding → buffer shape mismatch
            #     on long prompts (eval crash). So when speculation is on we
            #     must turn flash_attn off.
            #   • Quantized KV cache (Q4/Q8) REQUIRES flash_attn=True. So when
            #     speculation is on we must also fall back to FP16 KV.
            # Trade-off: speculation gives a generation speedup; FP16 KV halves
            # the effective context. User picks via MAXCODER_SPECULATIVE_MODE.
            use_flash  = (draft is None)
            kv_for_run = KV_CACHE_TYPE if use_flash else "fp16"
            kv_type_id = _GGML_TYPES.get(kv_for_run, 1)

            cls._instance = Llama(
                model_path     = path,
                n_gpu_layers   = GPU_LAYERS.get(name, 0),
                n_ctx          = N_CTX,
                type_k         = kv_type_id,
                type_v         = kv_type_id,
                flash_attn     = use_flash,
                draft_model    = draft,
                verbose        = False,
            )

            # Attach the prefix cache so repeated prompt prefixes
            # (system prompt + RAG + history) skip re-evaluation. The cache
            # operates BELOW the response cache: the response cache short-
            # circuits identical (messages, options, model) tuples; the
            # prefix cache helps when only the trailing user turn differs.
            cache_kind = "off"
            try:
                from llama_cpp.llama_cache import LlamaRAMCache, LlamaDiskCache
                if PREFIX_CACHE_MODE == "ram":
                    cls._instance.set_cache(LlamaRAMCache(capacity_bytes=PREFIX_CACHE_BYTES))
                    cache_kind = f"ram({PREFIX_CACHE_BYTES // (1024*1024)}MB)"
                elif PREFIX_CACHE_MODE == "disk":
                    cache_dir = str(Path(__file__).resolve().parent.parent / PREFIX_CACHE_DIR)
                    cls._instance.set_cache(LlamaDiskCache(cache_dir=cache_dir,
                                                            capacity_bytes=PREFIX_CACHE_BYTES))
                    cache_kind = f"disk({PREFIX_CACHE_BYTES // (1024*1024)}MB → {cache_dir})"
            except Exception as e:
                import sys
                print(f"[llm_backend] prefix cache setup failed: {e}",
                      file=sys.stderr, flush=True)

            cls._instance_name = name
            cls._draft         = draft
            cls._draft_kind    = draft_kind
            cls._prefix_cache_kind = cache_kind
            import sys
            print(f"[llm_backend] loaded {name} in {time.time()-t0:.1f}s "
                  f"(gpu_layers={GPU_LAYERS.get(name, 0)}, n_ctx={N_CTX}, "
                  f"kv={KV_CACHE_TYPE}, speculation={draft_kind or 'off'}, "
                  f"prefix_cache={cache_kind})",
                  file=sys.stderr, flush=True)
            return cls._instance

    @classmethod
    def _unload_unlocked(cls) -> None:
        """Free current model + draft. MUST be called with _lock held."""
        if cls._instance is not None:
            try:
                cls._instance.close()
            except Exception:
                pass
            cls._instance = None
            cls._instance_name = ""
        # The draft may be a Llama (needs close) or a lookup helper (no-op)
        if cls._draft is not None and hasattr(cls._draft, "close"):
            try:
                cls._draft.close()
            except Exception:
                pass
        cls._draft = None
        cls._draft_kind = ""

    @classmethod
    def unload(cls) -> None:
        """Free the currently-loaded model. Useful for tests."""
        with cls._lock:
            cls._unload_unlocked()

    @classmethod
    def info(cls) -> dict:
        return {
            "loaded":      cls._instance_name or None,
            "available":   list(MODEL_PATHS.keys()),
            "n_ctx":       N_CTX,
            "kv_cache":    KV_CACHE_TYPE,
            "gpu_layers":  dict(GPU_LAYERS),
            "speculation": {
                "mode":         SPECULATIVE_MODE,
                "active":       cls._draft_kind or "off",
                "pred_tokens":  SPECULATIVE_PRED_TOKENS,
                "ngram_size":   SPECULATIVE_NGRAM,
            },
            "prefix_cache": {
                "mode":   PREFIX_CACHE_MODE,
                "active": cls._prefix_cache_kind,
                "bytes":  PREFIX_CACHE_BYTES,
            },
        }


# ── Option mapping (Ollama-style → llama-cpp kwargs) ────────────────────────
def _map_options(options: Optional[dict]) -> dict:
    """Translate the option keys the rest of the codebase uses (Ollama names)
    into llama-cpp kwargs. Anything not in the whitelist is dropped silently."""
    if not options:
        return {}
    out: dict = {}
    if "num_predict"    in options: out["max_tokens"]       = options["num_predict"]
    if "temperature"    in options: out["temperature"]      = options["temperature"]
    if "top_p"          in options: out["top_p"]            = options["top_p"]
    if "top_k"          in options: out["top_k"]            = options["top_k"]
    if "repeat_penalty" in options: out["repeat_penalty"]   = options["repeat_penalty"]
    if "stop"           in options: out["stop"]             = options["stop"]
    if "seed"           in options: out["seed"]             = options["seed"]
    # num_ctx is a model-load option, not a per-call option — ignored here
    return out


# ── Public API ──────────────────────────────────────────────────────────────
def _sync_generate(messages: list[dict], model_name: str,
                    options: Optional[dict]) -> str:
    """Blocking call into llama-cpp. Runs in a thread from async wrappers."""
    llm = _ModelManager.get(model_name)
    out = llm.create_chat_completion(
        messages=messages,
        stream=False,
        **_map_options(options),
    )
    return out["choices"][0]["message"]["content"]


async def generate(messages:  list[dict],
                    model:     Optional[str] = None,
                    options:   Optional[dict] = None,
                    use_cache: bool          = True) -> str:
    """Non-streaming generation. Drop-in compatible with the old Ollama
    wrapper. Returns the full response as a string."""
    name = _resolve_name(model)

    if use_cache:
        cached = _cache_lookup(messages, options, name)
        if cached is not None:
            return cached

    full = await asyncio.to_thread(_sync_generate, messages, name, options)

    if use_cache and full:
        _cache_store(messages, options, name, full)
    return full


def _sync_stream(messages: list[dict], model_name: str,
                  options: Optional[dict]):
    """Blocking generator from llama-cpp. Iterated by the async wrapper."""
    llm = _ModelManager.get(model_name)
    yield from llm.create_chat_completion(
        messages=messages,
        stream=True,
        **_map_options(options),
    )


async def stream(messages:  list[dict],
                  model:     Optional[str] = None,
                  options:   Optional[dict] = None,
                  use_cache: bool          = True) -> AsyncIterator[str]:
    """Streaming generation. Yields string tokens as they're produced.

    On cache hit, replays the cached response in 48-char chunks so the
    consumer's incremental-render pipeline still works.
    """
    name = _resolve_name(model)

    if use_cache:
        cached = _cache_lookup(messages, options, name)
        if cached is not None:
            CHUNK = 48
            for i in range(0, len(cached), CHUNK):
                yield cached[i:i + CHUNK]
            return

    # Use a thread + queue to bridge sync generator → async iterator.
    # llama-cpp's stream API is a Python generator; we drain it from a worker
    # thread and push tokens into an asyncio queue.
    loop  = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    SENTINEL = object()

    def _producer():
        try:
            for chunk in _sync_stream(messages, name, options):
                delta = chunk["choices"][0]["delta"].get("content", "")
                if delta:
                    asyncio.run_coroutine_threadsafe(queue.put(delta), loop).result()
        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                queue.put(f"\n[stream error: {type(e).__name__}: {e}]"), loop
            ).result()
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(SENTINEL), loop).result()

    producer_task = loop.run_in_executor(None, _producer)

    full = ""
    while True:
        tok = await queue.get()
        if tok is SENTINEL:
            break
        full += tok
        yield tok

    await producer_task
    if use_cache and full:
        _cache_store(messages, options, name, full)


# ── Diagnostics ─────────────────────────────────────────────────────────────
def backend_info() -> dict:
    """Inspect the loaded backend — useful for /health endpoints."""
    return {
        "backend":     "llama-cpp-python",
        "manager":     _ModelManager.info(),
    }
