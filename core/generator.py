"""
Thin async wrapper around Ollama /api/chat.
Supports both streaming and non-streaming modes.
"""
from __future__ import annotations
import os, json
import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.getenv("MAXCODER_MODEL", "maxcoder-fast")


async def generate(messages: list[dict], model: str | None = None) -> str:
    """Non-streaming: return full response as string."""
    m = model or DEFAULT_MODEL
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": m, "messages": messages, "stream": False},
        )
        r.raise_for_status()
        return r.json()["message"]["content"]


async def stream(messages: list[dict], model: str | None = None):
    """Async generator — yields string tokens one by one."""
    m = model or DEFAULT_MODEL
    async with httpx.AsyncClient(timeout=None) as c:
        async with c.stream(
            "POST",
            f"{OLLAMA_URL}/api/chat",
            json={"model": m, "messages": messages, "stream": True},
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
