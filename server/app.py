"""
MaxCoder v2 FastAPI backend — with Phase 1 Agent endpoints.
"""
from __future__ import annotations

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional

from core.generator      import stream as llm_stream, generate
from core.query_rewriter import rewrite
from core.memory         import retrieve as mem_retrieve, save as mem_save, list_all as mem_list
from core.rag_retriever  import retrieve as rag_retrieve
from core.prompt_builder import build as build_prompt, agent_build
from core.critic         import critique_and_fix
from core.executor       import execute_and_fix, run_snippet
from core.tools          import parse_tool_calls, dispatch
from core.web_search     import web_context, should_search
from core.workspace      import (
    get_or_create_project, list_projects, delete_project,
    read_file, write_file, delete_file, list_files,
    project_context_snapshot,
)
from core.agent_parser   import parse_agent_response

app = FastAPI(title="MaxCoder v2")


# ── Shared models ─────────────────────────────────────────────────────────────

class Msg(BaseModel):
    role:    str
    content: str

class ChatReq(BaseModel):
    messages:       List[Msg]
    model:          Optional[str] = None
    use_rag:        bool = True
    use_memory:     bool = True
    use_rewriter:   bool = True
    use_critic:     bool = False
    use_web_search: bool = True
    auto_execute:   bool = False

class MemoryReq(BaseModel):
    text:     str
    category: str = "general"

class RunReq(BaseModel):
    code: str
    lang: str = "python"

class SearchReq(BaseModel):
    query: str


# ── Agent models ──────────────────────────────────────────────────────────────

class AgentChatReq(BaseModel):
    project_id:  str
    messages:    List[Msg]
    model:       Optional[str] = None
    use_memory:  bool = True
    auto_run:    bool = True
    project_name: Optional[str] = None

class FileWriteReq(BaseModel):
    content: str

class ProjectCreateReq(BaseModel):
    project_id:   str
    project_name: Optional[str] = None


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r      = await c.get(f"{os.getenv('OLLAMA_URL','http://127.0.0.1:11434')}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            return {"ok": True, "ollama": "up", "models": models}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Standard chat (unchanged) ─────────────────────────────────────────────────

@app.post("/chat")
async def chat(req: ChatReq):
    msgs_raw   = [m.model_dump() for m in req.messages]
    user_query = next((m["content"] for m in reversed(msgs_raw) if m["role"] == "user"), "")
    history    = [m for m in msgs_raw if m["role"] in ("user", "assistant")][:-1]

    if req.use_rewriter and user_query:
        user_query = await rewrite(user_query)

    web_ctx = ""
    if req.use_web_search and should_search(user_query):
        web_ctx = await web_context(user_query)

    mem_ctx = mem_retrieve(user_query) if req.use_memory else ""
    rag_ctx = rag_retrieve(user_query) if req.use_rag    else ""

    augmented_query = f"{web_ctx}\n\n{user_query}".strip() if web_ctx else user_query
    messages = build_prompt(augmented_query, history, mem_ctx, rag_ctx)

    async def gen():
        full = ""
        if web_ctx:
            yield "*Searched the web for latest docs...*\n\n"
        async for tok in llm_stream(messages, model=req.model):
            full += tok
            yield tok
        for call in parse_tool_calls(full):
            result = await dispatch(call)
            yield f"\n\n**Tool `{call['tool']}` result:**\n```\n{result}\n```"

    return StreamingResponse(gen(), media_type="text/plain")


@app.post("/chat_full")
async def chat_full(req: ChatReq):
    msgs_raw   = [m.model_dump() for m in req.messages]
    user_query = next((m["content"] for m in reversed(msgs_raw) if m["role"] == "user"), "")
    history    = [m for m in msgs_raw if m["role"] in ("user", "assistant")][:-1]

    if req.use_rewriter:
        user_query = await rewrite(user_query)

    web_ctx = await web_context(user_query) if req.use_web_search and should_search(user_query) else ""
    mem_ctx = mem_retrieve(user_query) if req.use_memory else ""
    rag_ctx = rag_retrieve(user_query) if req.use_rag    else ""

    augmented_query = f"{web_ctx}\n\n{user_query}".strip() if web_ctx else user_query
    messages = build_prompt(augmented_query, history, mem_ctx, rag_ctx)

    draft        = await generate(messages, model=req.model)
    critique_log = []
    if req.use_critic:
        draft, critique_log = await critique_and_fix(draft, model=req.model)

    return {"response": draft, "critique_log": critique_log, "web_searched": bool(web_ctx)}


# ── Agent endpoints ───────────────────────────────────────────────────────────

@app.post("/agent/chat")
async def agent_chat(req: AgentChatReq):
    """
    Agentic chat endpoint.
    - Injects full project file snapshot into every prompt
    - Parses CREATE/EDIT/DELETE/RUN commands from LLM response
    - Applies file operations to workspace/<project_id>/
    - Streams the response token by token
    - Returns applied operations as a trailing JSON event
    """
    # Ensure project exists
    get_or_create_project(req.project_id, req.project_name or req.project_id)

    msgs_raw   = [m.model_dump() for m in req.messages]
    user_query = next((m["content"] for m in reversed(msgs_raw) if m["role"] == "user"), "")
    history    = [m for m in msgs_raw if m["role"] in ("user", "assistant")][:-1]

    mem_ctx  = mem_retrieve(user_query) if req.use_memory else ""
    snapshot = project_context_snapshot(req.project_id)
    messages = agent_build(user_query, history, snapshot, mem_ctx)

    async def gen():
        import json as _json

        full = ""
        async for tok in llm_stream(messages, model=req.model):
            full += tok
            yield tok

        # Parse and apply file operations
        ops, _ = parse_agent_response(full)
        applied = []

        for op in ops:
            try:
                if op.op in ("create", "edit"):
                    result = write_file(req.project_id, op.path, op.content)
                    applied.append({"op": op.op, "path": op.path, "ok": True, "msg": result})

                elif op.op == "delete":
                    result = delete_file(req.project_id, op.path)
                    applied.append({"op": op.op, "path": op.path, "ok": True, "msg": result})

                elif op.op == "run" and req.auto_run:
                    run_result = run_snippet(op.content, op.lang, auto_install=True)
                    applied.append({
                        "op":     "run",
                        "path":   "",
                        "lang":   op.lang,
                        "ok":     run_result.get("ok", False),
                        "stdout": run_result.get("stdout", ""),
                        "stderr": run_result.get("stderr", ""),
                        "preview_html": run_result.get("preview_html"),
                    })
            except Exception as e:
                applied.append({"op": op.op, "path": op.path, "ok": False, "msg": str(e)})

        # Emit file list update + applied ops as a special trailing event
        if applied:
            files_now = list_files(req.project_id)
            event = {
                "event":    "ops",
                "applied":  applied,
                "files":    files_now,
                "project_id": req.project_id,
            }
            yield f"\n\n@@EVENT:{_json.dumps(event)}"

    return StreamingResponse(gen(), media_type="text/plain")


@app.get("/agent/projects")
async def agent_list_projects():
    return {"projects": list_projects()}


@app.post("/agent/projects")
async def agent_create_project(req: ProjectCreateReq):
    meta = get_or_create_project(req.project_id, req.project_name or req.project_id)
    return meta


@app.delete("/agent/projects/{project_id}")
async def agent_delete_project(project_id: str):
    ok = delete_project(project_id)
    return {"ok": ok}


@app.get("/agent/projects/{project_id}/files")
async def agent_list_files(project_id: str):
    return {"files": list_files(project_id)}


@app.get("/agent/projects/{project_id}/files/{file_path:path}")
async def agent_read_file(project_id: str, file_path: str):
    content = read_file(project_id, file_path)
    if content.startswith("ERROR:"):
        raise HTTPException(status_code=404, detail=content)
    return {"path": file_path, "content": content}


@app.put("/agent/projects/{project_id}/files/{file_path:path}")
async def agent_write_file(project_id: str, file_path: str, req: FileWriteReq):
    result = write_file(project_id, file_path, req.content)
    files  = list_files(project_id)
    return {"ok": True, "msg": result, "files": files}


@app.delete("/agent/projects/{project_id}/files/{file_path:path}")
async def agent_delete_file(project_id: str, file_path: str):
    result = delete_file(project_id, file_path)
    files  = list_files(project_id)
    return {"ok": not result.startswith("ERROR"), "msg": result, "files": files}


# ── Code runner ───────────────────────────────────────────────────────────────

@app.post("/run")
async def run(req: RunReq):
    return run_snippet(req.code, req.lang, auto_install=True)


# ── Web search ────────────────────────────────────────────────────────────────

@app.post("/search")
async def search(req: SearchReq):
    ctx = await web_context(req.query)
    return {"context": ctx, "found": bool(ctx)}


# ── Memory ────────────────────────────────────────────────────────────────────

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
