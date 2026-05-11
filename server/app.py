"""
MaxCoder v2 FastAPI backend — with Web Search + Eval layers.

Pipeline per request:
  1. Query Rewrite
  2. Web Search (if needed)
  3. Memory retrieval
  4. RAG retrieval
  5. Prompt assembly (CoT)
  6. LLM generation (streaming or full)
  7. Self-critique loop  (optional)
  8. Code execution loop (optional)
"""
from __future__ import annotations
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional

from core.generator      import stream as llm_stream, generate
from core.query_rewriter import rewrite
from core.memory         import retrieve as mem_retrieve, save as mem_save, list_all as mem_list
from core.rag_retriever  import retrieve as rag_retrieve
from core.prompt_builder import build as build_prompt
from core.critic         import critique_and_fix
from core.executor       import execute_and_fix
from core.tools          import parse_tool_calls, dispatch
from core.web_search     import web_context, should_search

app = FastAPI(title="MaxCoder v2")

# ── Schemas ───────────────────────────────────────────────────────────────────
class Msg(BaseModel):
    role: str
    content: str

class ChatReq(BaseModel):
    messages: List[Msg]
    model: Optional[str] = None
    use_rag: bool = True
    use_memory: bool = True
    use_rewriter: bool = True
    use_critic: bool = False
    use_web_search: bool = True      # NEW
    auto_execute: bool = False

class MemoryReq(BaseModel):
    text: str
    category: str = "general"

class RunReq(BaseModel):
    code: str
    lang: str = "python"

class SearchReq(BaseModel):
    query: str

# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{os.getenv('OLLAMA_URL','http://127.0.0.1:11434')}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
        return {"ok": True, "ollama": "up", "models": models}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ── Streaming chat ─────────────────────────────────────────────────────────────
@app.post("/chat")
async def chat(req: ChatReq):
    msgs_raw   = [m.model_dump() for m in req.messages]
    user_query = next(
        (m["content"] for m in reversed(msgs_raw) if m["role"] == "user"), "")
    history    = [m for m in msgs_raw if m["role"] in ("user", "assistant")][:-1]

    # 1. Query rewrite
    if req.use_rewriter and user_query:
        user_query = await rewrite(user_query)

    # 2. Web search
    web_ctx = ""
    if req.use_web_search and should_search(user_query):
        web_ctx = await web_context(user_query)

    # 3. Memory
    mem_ctx = mem_retrieve(user_query) if req.use_memory else ""

    # 4. RAG
    rag_ctx = rag_retrieve(user_query) if req.use_rag else ""

    # 5. Combine contexts
    combined_ctx = "\n\n".join(filter(None, [web_ctx, mem_ctx, rag_ctx]))

    # 6. Build prompt
    messages = build_prompt(user_query, history, mem_ctx, combined_ctx)

    # 7. Stream
    async def gen():
        full = ""
        # Show search indicator if web search ran
        if web_ctx:
            yield "🌐 *Searched the web for latest docs...*\n\n"
        async for tok in llm_stream(messages, model=req.model):
            full += tok
            yield tok
        # Tool dispatch
        for call in parse_tool_calls(full):
            result = await dispatch(call)
            yield f"\n\n**Tool `{call['tool']}` result:**\n```\n{result}\n```"

    return StreamingResponse(gen(), media_type="text/plain")


# ── Full (non-streaming) with critic ──────────────────────────────────────────
@app.post("/chat_full")
async def chat_full(req: ChatReq):
    msgs_raw   = [m.model_dump() for m in req.messages]
    user_query = next(
        (m["content"] for m in reversed(msgs_raw) if m["role"] == "user"), "")
    history    = [m for m in msgs_raw if m["role"] in ("user", "assistant")][:-1]

    if req.use_rewriter and user_query:
        user_query = await rewrite(user_query)

    web_ctx  = await web_context(user_query) if req.use_web_search and should_search(user_query) else ""
    mem_ctx  = mem_retrieve(user_query) if req.use_memory else ""
    rag_ctx  = rag_retrieve(user_query) if req.use_rag else ""
    combined = "\n\n".join(filter(None, [web_ctx, mem_ctx, rag_ctx]))
    messages = build_prompt(user_query, history, mem_ctx, combined)

    draft = await generate(messages, model=req.model)

    critique_log = []
    if req.use_critic:
        draft, critique_log = await critique_and_fix(draft, model=req.model)

    exec_result = None
    if req.auto_execute:
        for lang in ["python", "javascript", "bash"]:
            exec_result = await execute_and_fix(draft, lang, model=req.model)
            if exec_result.get("code"):
                break

    return {"response": draft, "critique_log": critique_log,
            "exec_result": exec_result, "web_searched": bool(web_ctx)}


# ── Manual web search endpoint ─────────────────────────────────────────────────
@app.post("/search")
async def search(req: SearchReq):
    ctx = await web_context(req.query)
    return {"context": ctx, "found": bool(ctx)}


# ── Execute code ───────────────────────────────────────────────────────────────
@app.post("/run")
async def run(req: RunReq):
    from core.executor import run_snippet
    return run_snippet(req.code, req.lang)


# ── Memory endpoints ───────────────────────────────────────────────────────────
@app.post("/memory/add")
async def memory_add(req: MemoryReq):
    mem_save(req.text, req.category)
    return {"ok": True}

@app.get("/memory/list")
async def memory_list():
    return {"memories": mem_list()}

@app.delete("/memory/clear")
async def memory_clear():
    from core.memory import delete_all
    delete_all()
    return {"ok": True}
