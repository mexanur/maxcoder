"""
MaxCoder v2 FastAPI backend — Phase 3.
New endpoints: /agent/sql, /agent/history, /agent/history/restore
Smart context: uses context_selector for relevant file injection.
"""
from __future__ import annotations

import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import List, Optional, Any

from core.generator       import stream as llm_stream, generate
from core.query_rewriter  import rewrite
from core.memory          import retrieve as mem_retrieve, save as mem_save, list_all as mem_list
from core.rag_retriever   import retrieve as rag_retrieve
from core.prompt_builder  import build as build_prompt, agent_build
from core.critic          import critique_and_fix
from core.executor        import execute_and_fix, run_snippet
from core.tools           import parse_tool_calls, dispatch
from core.web_search      import web_context, should_search, extract_urls, fetch_url_context
from core.workspace       import (
    get_or_create_project, list_projects, delete_project,
    read_file, write_file, delete_file, list_files,
    project_context_snapshot,
)
from core.agent_parser    import parse_agent_response
from core.sql_runner      import run_sql, list_tables, describe_table
from core.file_history    import (
    list_snapshots, restore_snapshot, get_snapshot_content,
)
from core.file_parser    import parse_file
from core.file_generator import generate_file, FORMATS
from core.reasoner       import reason_stream, classify as classify_task
from core.feedback       import (
    save_positive  as fb_save_positive,
    save_negative  as fb_save_negative,
    list_feedback  as fb_list,
    delete_feedback as fb_delete,
    stats          as fb_stats,
)

# Smart context selector (falls back to full snapshot if unavailable)
try:
    from core.context_selector import smart_snapshot
    _SMART_CTX = True
except Exception:
    _SMART_CTX = False


def _get_snapshot(project_id: str, query: str) -> str:
    if _SMART_CTX:
        try:
            return smart_snapshot(project_id, query)
        except Exception:
            pass
    return project_context_snapshot(project_id)


app = FastAPI(title="MaxCoder v2")


# ── Models ────────────────────────────────────────────────────────────────────

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
    use_reasoning:  bool = False     # MaxThink reasoning pipeline
    auto_execute:   bool = False

class MemoryReq(BaseModel):
    text:     str
    category: str = "general"

class RunReq(BaseModel):
    code: str
    lang: str = "python"

class SearchReq(BaseModel):
    query: str

class AgentChatReq(BaseModel):
    project_id:   str
    messages:     List[Msg]
    model:        Optional[str] = None
    use_memory:   bool = True
    auto_run:     bool = True
    project_name: Optional[str] = None

class FileWriteReq(BaseModel):
    content: str

class ProjectCreateReq(BaseModel):
    project_id:   str
    project_name: Optional[str] = None

class SqlReq(BaseModel):
    sql: str

class GenFileReq(BaseModel):
    content:  str
    fmt:      str = "txt"
    filename: str = "maxcoder_output"

class FeedbackPosReq(BaseModel):
    query:    str
    response: str
    model:    Optional[str] = ""
    files:    Optional[List[Any]] = None

class FeedbackNegReq(BaseModel):
    query:    str
    response: str
    reason:   Optional[str] = ""
    model:    Optional[str] = ""


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r      = await c.get(f"{os.getenv('OLLAMA_URL','http://127.0.0.1:11434')}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            return {"ok": True, "ollama": "up", "models": models,
                    "smart_context": _SMART_CTX}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Standard chat ─────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(req: ChatReq):
    msgs_raw   = [m.model_dump() for m in req.messages]
    user_query = next((m["content"] for m in reversed(msgs_raw) if m["role"] == "user"), "")
    history    = [m for m in msgs_raw if m["role"] in ("user", "assistant")][:-1]

    if req.use_rewriter and user_query:
        user_query = await rewrite(user_query)

    web_ctx = ""
    if req.use_web_search:
        direct_urls = extract_urls(user_query)
        if direct_urls:
            web_ctx = await fetch_url_context(direct_urls)
        elif should_search(user_query):
            web_ctx = await web_context(user_query)

    mem_ctx = mem_retrieve(user_query) if req.use_memory else ""
    rag_ctx = rag_retrieve(user_query) if req.use_rag    else ""

    augmented_query = f"{web_ctx}\n\n{user_query}".strip() if web_ctx else user_query

    # ── MaxThink reasoning pipeline ─────────────────────────────────────────
    if req.use_reasoning:
        import json as _json
        # Build a context string from RAG + memory + web for the reasoner
        ctx_parts = [c for c in (web_ctx, mem_ctx, rag_ctx) if c]
        ctx_str   = "\n\n".join(ctx_parts)
        strong    = req.model or "maxcoder"

        async def gen_reason():
            async for ev in reason_stream(
                query=augmented_query, context=ctx_str, strong_model=strong,
            ):
                # Emit events as JSON-lines so the frontend can render stages
                yield f"@@THINK_EVENT:{_json.dumps(ev, ensure_ascii=False)}\n"
        return StreamingResponse(gen_reason(), media_type="text/plain")

    # ── Regular non-reasoning chat ──────────────────────────────────────────
    messages = build_prompt(augmented_query, history, mem_ctx, rag_ctx)

    async def gen():
        full = ""
        if web_ctx:
            direct_urls = extract_urls(user_query)
            yield ("*Fetched the page...*\n\n" if direct_urls else "*Searched the web...*\n\n")
        async for tok in llm_stream(messages, model=req.model):
            full += tok
            yield tok
        for call in parse_tool_calls(full):
            result = await dispatch(call)
            yield f"\n\n**Tool `{call['tool']}` result:**\n```\n{result}\n```"

    return StreamingResponse(gen(), media_type="text/plain")


# Auto-classify endpoint — frontend can call this to know task type before chat
@app.post("/classify")
async def classify_endpoint(req: SearchReq):
    return {"task_type": classify_task(req.query)}


@app.post("/chat_full")
async def chat_full(req: ChatReq):
    msgs_raw   = [m.model_dump() for m in req.messages]
    user_query = next((m["content"] for m in reversed(msgs_raw) if m["role"] == "user"), "")
    history    = [m for m in msgs_raw if m["role"] in ("user", "assistant")][:-1]

    if req.use_rewriter:
        user_query = await rewrite(user_query)

    if req.use_web_search:
        direct_urls = extract_urls(user_query)
        web_ctx = await fetch_url_context(direct_urls) if direct_urls else (
            await web_context(user_query) if should_search(user_query) else ""
        )
    else:
        web_ctx = ""
    mem_ctx = mem_retrieve(user_query) if req.use_memory else ""
    rag_ctx = rag_retrieve(user_query) if req.use_rag    else ""

    augmented_query = f"{web_ctx}\n\n{user_query}".strip() if web_ctx else user_query
    messages = build_prompt(augmented_query, history, mem_ctx, rag_ctx)

    draft        = await generate(messages, model=req.model)
    critique_log = []
    if req.use_critic:
        draft, critique_log = await critique_and_fix(draft, model=req.model)

    return {"response": draft, "critique_log": critique_log, "web_searched": bool(web_ctx)}


# ── Agent chat ────────────────────────────────────────────────────────────────

@app.post("/agent/chat")
async def agent_chat(req: AgentChatReq):
    get_or_create_project(req.project_id, req.project_name or req.project_id)

    msgs_raw   = [m.model_dump() for m in req.messages]
    user_query = next((m["content"] for m in reversed(msgs_raw) if m["role"] == "user"), "")
    history    = [m for m in msgs_raw if m["role"] in ("user", "assistant")][:-1]

    mem_ctx  = mem_retrieve(user_query) if req.use_memory else ""
    # Phase 3: smart context — only inject relevant files
    snapshot = _get_snapshot(req.project_id, user_query)
    messages = agent_build(user_query, history, snapshot, mem_ctx)

    async def gen():
        import json as _json

        full = ""
        async for tok in llm_stream(messages, model=req.model):
            full += tok
            yield tok

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

        if applied:
            files_now = list_files(req.project_id)
            event = {
                "event":      "ops",
                "applied":    applied,
                "files":      files_now,
                "project_id": req.project_id,
                "smart_ctx":  _SMART_CTX,
            }
            yield f"\n\n@@EVENT:{_json.dumps(event)}"

    return StreamingResponse(gen(), media_type="text/plain")


# ── Agent projects ────────────────────────────────────────────────────────────

@app.get("/agent/projects")
async def agent_list_projects():
    return {"projects": list_projects()}

@app.post("/agent/projects")
async def agent_create_project(req: ProjectCreateReq):
    return get_or_create_project(req.project_id, req.project_name or req.project_id)

@app.delete("/agent/projects/{project_id}")
async def agent_delete_project(project_id: str):
    return {"ok": delete_project(project_id)}


# ── Agent files ───────────────────────────────────────────────────────────────

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
    return {"ok": True, "msg": result, "files": list_files(project_id)}

@app.delete("/agent/projects/{project_id}/files/{file_path:path}")
async def agent_delete_file(project_id: str, file_path: str):
    result = delete_file(project_id, file_path)
    return {"ok": not result.startswith("ERROR"), "msg": result,
            "files": list_files(project_id)}


# ── File history (undo) ───────────────────────────────────────────────────────

@app.get("/agent/projects/{project_id}/history/{file_path:path}")
async def agent_file_history(project_id: str, file_path: str):
    snaps = list_snapshots(project_id, file_path)
    return {"path": file_path, "snapshots": snaps}

@app.get("/agent/projects/{project_id}/history/{file_path:path}/{stamp}")
async def agent_get_snapshot(project_id: str, file_path: str, stamp: str):
    content = get_snapshot_content(project_id, file_path, stamp)
    if content.startswith("ERROR:"):
        raise HTTPException(status_code=404, detail=content)
    return {"path": file_path, "stamp": stamp, "content": content}

@app.post("/agent/projects/{project_id}/history/{file_path:path}/{stamp}/restore")
async def agent_restore_snapshot(project_id: str, file_path: str, stamp: str):
    msg  = restore_snapshot(project_id, file_path, stamp)
    ok   = not msg.startswith("ERROR")
    return {"ok": ok, "msg": msg, "files": list_files(project_id)}


# ── SQL runner ────────────────────────────────────────────────────────────────

@app.post("/agent/projects/{project_id}/sql")
async def agent_run_sql(project_id: str, req: SqlReq):
    return run_sql(project_id, req.sql)

@app.get("/agent/projects/{project_id}/sql/tables")
async def agent_list_tables(project_id: str):
    return {"tables": list_tables(project_id)}

@app.get("/agent/projects/{project_id}/sql/tables/{table}")
async def agent_describe_table(project_id: str, table: str):
    return {"table": table, "columns": describe_table(project_id, table)}


# ── Code runner ───────────────────────────────────────────────────────────────

@app.post("/run")
async def run(req: RunReq):
    return run_snippet(req.code, req.lang, auto_install=True)


# ── File generation ───────────────────────────────────────────────────────────

@app.post("/generate-file")
async def generate_file_endpoint(req: GenFileReq):
    try:
        data, mime, ext = generate_file(req.fmt, req.content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    safe_name = re.sub(r'[^\w\-.]', '_', req.filename) + ext
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )

@app.get("/generate-file/formats")
async def list_formats():
    return {"formats": list(FORMATS.keys())}


# ── File upload / parsing ─────────────────────────────────────────────────────

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    data = await file.read()
    text = parse_file(file.filename or "file", data)
    return {
        "name":  file.filename,
        "size":  len(data),
        "text":  text,
        "chars": len(text),
    }


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


# ── Feedback / conversation capture ───────────────────────────────────────────

@app.post("/feedback/positive")
async def feedback_positive(req: FeedbackPosReq):
    """Thumbs-up: persist + index for future retrieval."""
    entry = fb_save_positive(
        query    = req.query,
        response = req.response,
        model    = req.model or "",
        files    = req.files or [],
    )
    return {"ok": True, "id": entry["id"], "indexed": entry.get("indexed", False)}

@app.post("/feedback/negative")
async def feedback_negative(req: FeedbackNegReq):
    """Thumbs-down: persist for review only — NOT indexed."""
    entry = fb_save_negative(
        query    = req.query,
        response = req.response,
        reason   = req.reason or "",
        model    = req.model or "",
    )
    return {"ok": True, "id": entry["id"]}

@app.get("/feedback/list")
async def feedback_list(kind: str = "all", limit: int = 50):
    return {"entries": fb_list(kind=kind, limit=limit)}

@app.delete("/feedback/{fid}")
async def feedback_delete(fid: str):
    return {"ok": fb_delete(fid)}

@app.get("/feedback/stats")
async def feedback_stats_endpoint():
    return fb_stats()
