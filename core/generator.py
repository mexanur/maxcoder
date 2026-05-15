"""
Thin async wrapper around Ollama /api/chat.
Supports both streaming and non-streaming modes.
"""
from __future__ import annotations
import os, json
import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.getenv("MAXCODER_MODEL", "maxcoder-fast")


def _build_payload(model: str, messages: list[dict], options: dict | None) -> dict:
    """Build Ollama /api/chat payload with optional inference options."""
    p = {"model": model, "messages": messages, "stream": True}
    if options:
        # Filter to only the keys Ollama supports
        valid = {k: v for k, v in options.items() if k in {
            "num_predict", "temperature", "top_p", "top_k",
            "repeat_penalty", "stop", "num_ctx", "seed",
        }}
        if valid:
            p["options"] = valid
    return p


async def generate(
    messages: list[dict],
    model:    str | None = None,
    options:  dict | None = None,
) -> str:
    """Non-streaming: return full response as string. Streams internally so the
    connection stays alive on slow hardware, then accumulates."""
    m = model or DEFAULT_MODEL
    full = ""
    async with httpx.AsyncClient(timeout=None) as c:
        async with c.stream(
            "POST",
            f"{OLLAMA_URL}/api/chat",
            json=_build_payload(m, messages, options),
        ) as r:
            async for line in r.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    tok = chunk.get("message", {}).get("content", "")
                    if tok:
                        full += tok
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue
    return full


async def stream(
    messages: list[dict],
    model:    str | None = None,
    options:  dict | None = None,
):
    """Async generator — yields string tokens one by one."""
    m = model or DEFAULT_MODEL
    async with httpx.AsyncClient(timeout=None) as c:
        async with c.stream(
            "POST",
            f"{OLLAMA_URL}/api/chat",
            json=_build_payload(m, messages, options),
        ) as r:
            async for line in r.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    tok = chunk.get("message", {}).get("content", "")
                    if tok:
                        yield tok
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue
