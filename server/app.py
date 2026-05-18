"""
MaxCoder v2 FastAPI backend — Phase 3.
New endpoints: /agent/sql, /agent/history, /agent/history/restore
Smart context: uses context_selector for relevant file injection.
"""
from __future__ import annotations

import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Silence ChromaDB telemetry BEFORE any module imports chromadb. Setting this
# inside individual core modules was too late — feedback.py / chat_memory.py
# import chromadb earlier in the import chain. Doing it here is bulletproof.
os.environ["ANONYMIZED_TELEMETRY"]      = "False"
os.environ["CHROMA_TELEMETRY_DISABLED"] = "True"

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
from core.reasoner       import reason_stream, classify as classify_task, looks_technical as _looks_technical
from core.skills          import find_matching_skill, run_skill, list_skills, SkillContext
from core.chat_memory     import extract_memory, resolve_references
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
        from core.web_navigator import cache_stats as _web_cache_stats
        page_cache = _web_cache_stats()
    except Exception:
        page_cache = {}
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r      = await c.get(f"{os.getenv('OLLAMA_URL','http://127.0.0.1:11434')}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            return {"ok": True, "ollama": "up", "models": models,
                    "smart_context": _SMART_CTX, "page_cache": page_cache}
    except Exception as e:
        return {"ok": False, "error": str(e), "page_cache": page_cache}


# Clear the in-memory page cache (useful when debugging stale pages)
@app.delete("/cache/pages")
async def cache_clear_pages():
    from core.web_navigator import cache_clear
    n = cache_clear()
    return {"ok": True, "removed": n}


# ── Translation learning (user-driven corpus growth) ──────────────────────────

class TransCandidateReq(BaseModel):
    source: str
    target: str            # the user's corrected translation
    lang:   str            # e.g. "uzbek", "russian", "french"
    draft:  Optional[str] = ""   # what the LLM originally produced (for audit)
    note:   Optional[str] = ""   # user comment

@app.post("/translation/candidates")
async def translation_submit(req: TransCandidateReq):
    """Submit a user correction. Auto-screened, then awaits manual approval."""
    from core.translation_learning import submit_candidate
    return submit_candidate(
        source = req.source, target = req.target, lang = req.lang,
        draft  = req.draft or "", note = req.note or "",
    )

@app.get("/translation/candidates")
async def translation_list(lang: Optional[str] = None, status: str = "pending", limit: int = 100):
    """List translation candidates (pending by default)."""
    from core.translation_learning import list_candidates
    return {"candidates": list_candidates(lang=lang, status=status, limit=limit)}

@app.post("/translation/candidates/{cid}/approve")
async def translation_approve(cid: str):
    """Promote a candidate to the live corpus."""
    from core.translation_learning import approve_candidate
    return approve_candidate(cid)

@app.post("/translation/candidates/{cid}/reject")
async def translation_reject(cid: str, reason: str = ""):
    """Reject a candidate (kept in audit log only)."""
    from core.translation_learning import reject_candidate
    return reject_candidate(cid, reason=reason)

@app.get("/translation/stats")
async def translation_stats():
    """Counts by language + status."""
    from core.translation_learning import stats
    from core.translation_memory import available_languages
    return {"candidates": stats(), "corpus": available_languages()}


# ── Standard chat ─────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(req: ChatReq):
    msgs_raw   = [m.model_dump() for m in req.messages]
    user_query = next((m["content"] for m in reversed(msgs_raw) if m["role"] == "user"), "")
    history    = [m for m in msgs_raw if m["role"] in ("user", "assistant")][:-1]

    # Preserve the original literal user input — rewriter would mutate it
    original_query = user_query

    # ── CHAT MEMORY ─────────────────────────────────────────────────────────
    # Extract entities (URLs, files) from prior history, then resolve any
    # references in the current query ("that website" → actual URL).
    chat_memory    = extract_memory(history)
    resolved_query = resolve_references(original_query, chat_memory)

    # ── MODEL ROUTING ───────────────────────────────────────────────────────
    # If the caller didn't pin a specific model, route by query complexity:
    # small model for trivial/conversational, big model for code/reasoning.
    # This is the single biggest throughput win on a 4GB-VRAM laptop because
    # the 3B runs ~3× faster than the 7B and most chat turns don't need 7B.
    from core.model_router import pick_model as _pick_model
    if not req.model:
        req.model = _pick_model(
            query=resolved_query, history=history,
            use_reasoning=req.use_reasoning,
        )

    # ── SKILL ROUTING ───────────────────────────────────────────────────────
    # Check skills BEFORE the normal LLM pipeline. Skills are deterministic
    # handlers for specific intents (file generation, code exec, etc.).
    skill_ctx = SkillContext(
        query         = resolved_query,
        history       = history,
        model         = req.model or "maxcoder-fast",
        chat_memory   = chat_memory,
        use_reasoning = req.use_reasoning,
    )
    matched = find_matching_skill(skill_ctx)
    if matched:
        import json as _json
        async def gen_skill():
            async for ev in run_skill(matched, skill_ctx):
                if ev.kind == "answer_chunk":
                    # Skills emit raw text tokens that become the visible answer
                    yield ev.content if isinstance(ev.content, str) else _json.dumps(ev.content)
                else:
                    # Each event marker is on its OWN LINE so the frontend
                    # can strip it via a line-bounded regex (avoids nested-JSON
                    # brace-matching issues with non-greedy regex).
                    payload = _json.dumps({"kind": ev.kind, "content": ev.content}, ensure_ascii=False)
                    yield f"\n@@SKILL_EVENT:{payload}\n"
        return StreamingResponse(gen_skill(), media_type="text/plain")

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

    # AUTO-ESCALATION: if RAG returned nothing AND the query is technical
    # AND we haven't already searched the web → trigger a web search to fill
    # the knowledge gap. Uses ORIGINAL query (not rewritten spec).
    if req.use_web_search and not web_ctx and not rag_ctx and _looks_technical(original_query):
        try:
            web_ctx = await web_context(original_query)
        except Exception:
            pass

    # Inject chat memory (URLs visited, files generated) as additional context.
    # Skill path already gets it via SkillContext.chat_memory; this is for the
    # non-skill fallback so plain LLM chat also has reference awareness.
    from core.chat_memory import memory_summary as _mem_summary
    chat_mem_text = _mem_summary(chat_memory, max_items=8)
    if chat_mem_text:
        mem_ctx = (mem_ctx + "\n\n" + chat_mem_text) if mem_ctx else chat_mem_text

    augmented_query = f"{web_ctx}\n\n{user_query}".strip() if web_ctx else user_query

    # ── MaxThink reasoning pipeline ─────────────────────────────────────────
    if req.use_reasoning:
        import json as _json
        # Build a context string from RAG + memory + web for the reasoner
        ctx_parts = [c for c in (web_ctx, mem_ctx, rag_ctx) if c]
        ctx_str   = "\n\n".join(ctx_parts)
        strong    = req.model or "maxcoder"

        # Classify on the user's LITERAL input — not the rewritten/augmented
        # version. Both the rewriter and web-search prepending can introduce
        # spurious technical keywords that bias the classifier.
        pre_task = classify_task(original_query)

        async def gen_reason():
            async for ev in reason_stream(
                query=augmented_query, context=ctx_str,
                task_type=pre_task, strong_model=strong,
            ):
                # Emit events as JSON-lines so the frontend can render stages
                yield f"@@THINK_EVENT:{_json.dumps(ev, ensure_ascii=False)}\n"
        return StreamingResponse(gen_reason(), media_type="text/plain")

    # ── Regular non-reasoning chat ──────────────────────────────────────────
    messages = build_prompt(augmented_query, history, mem_ctx, rag_ctx)

    # If the query is conversational (joke, fact, story, etc.) we run the
    # streamed tokens through a code-fence stripper so any stray ```...```
    # block the model emits is swallowed before reaching the user. Keeps
    # casual chats clean even when the coder-tuned base leaks CSS or JS.
    from core.prompt_builder import _is_conversational as _is_chat
    suppress_code = _is_chat(user_query)

    async def gen():
        import json as _json
        full = ""
        if web_ctx:
            direct_urls = extract_urls(user_query)
            yield ("*Fetched the page...*\n\n" if direct_urls else "*Searched the web...*\n\n")

        # Streaming fence filter state
        buf       = ""
        in_fence  = False
        async for tok in llm_stream(messages, model=req.model):
            full += tok
            if not suppress_code:
                yield tok
                continue
            # In suppress-code mode, accumulate tokens and emit only when we
            # know we're outside a fence. We need to buffer up to 4 chars at
            # the boundary so we can detect ``` reliably.
            buf += tok
            while buf:
                if in_fence:
                    end = buf.find("```")
                    if end == -1:
                        # Whole buffer is inside fence — keep waiting unless
                        # buffer is large enough that the rest can't be a fence opener
                        if len(buf) > 3:
                            buf = buf[-3:]   # keep last 3 chars (could be partial ```)
                        break
                    # Skip past the closing fence and continue
                    buf = buf[end + 3:]
                    in_fence = False
                else:
                    start = buf.find("```")
                    if start == -1:
                        # No fence in buffer — safe to emit all but the last 2
                        # chars (in case a fence is mid-arrival)
                        if len(buf) > 2:
                            yield buf[:-2]
                            buf = buf[-2:]
                        break
                    # Emit everything before the fence, then enter fence mode
                    if start > 0:
                        yield buf[:start]
                    buf = buf[start + 3:]
                    in_fence = True
        # Flush any leftover non-fence buffer
        if buf and not in_fence:
            yield buf
        for call in parse_tool_calls(full):
            result = await dispatch(call)
            yield f"\n\n**Tool `{call['tool']}` result:**\n```\n{result}\n```"

        # Uncertainty assessment — runs both hedge-detection AND a hallucination
        # audit (asks the model to list any library/API names and flag invented ones).
        # Adds ~5-10s but catches confident hallucinations that hedge-only misses.
        try:
            from core.uncertainty import assess as _assess
            uncert = await _assess(full, skip_verbalize=False)
            # Emit on its own line so frontend can match with line-bounded regex
            yield f"\n@@UNCERTAINTY:{_json.dumps(uncert.to_dict(), ensure_ascii=False)}\n"
        except Exception:
            pass

    return StreamingResponse(gen(), media_type="text/plain")


# Auto-classify endpoint — frontend can call this to know task type before chat
@app.post("/classify")
async def classify_endpoint(req: SearchReq):
    return {"task_type": classify_task(req.query)}


# List available skills — for UI to show "Skills" pane / autocomplete
@app.get("/skills")
async def skills_endpoint():
    return {"skills": list_skills()}


# Test which skill (if any) would match a given query
@app.post("/skills/match")
async def skills_match(req: SearchReq):
    ctx = SkillContext(query=req.query, history=[], model="maxcoder-fast")
    matched = find_matching_skill(ctx)
    return {"matched": matched.name if matched else None,
            "label":   matched.label if matched else None}


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


# ── Chat backup / restore ─────────────────────────────────────────────────────
# Lets the frontend export its entire localStorage state to a JSON file on disk
# (and restore later). Useful for archiving / cross-device sync / 1-month tests.
import json as _json_mod, pathlib as _pl, datetime as _dt

_BACKUP_DIR = _pl.Path(__file__).resolve().parent.parent / "chat_backups"
_BACKUP_DIR.mkdir(exist_ok=True)


class BackupReq(BaseModel):
    name:    Optional[str] = None
    payload: dict           # whatever the frontend wants to archive

@app.post("/chat/backup")
async def chat_backup(req: BackupReq):
    """Save a snapshot of frontend state to disk."""
    stamp  = _dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe   = re.sub(r"[^\w\-]", "_", req.name or "backup")
    fname  = f"{stamp}__{safe}.json"
    target = _BACKUP_DIR / fname
    target.write_text(
        _json_mod.dumps(req.payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"ok": True, "file": fname, "path": str(target)}

@app.get("/chat/backup/list")
async def chat_backup_list():
    """List available backups."""
    items = []
    for p in sorted(_BACKUP_DIR.glob("*.json"), reverse=True):
        items.append({
            "file":  p.name,
            "size":  p.stat().st_size,
            "mtime": _dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
        })
    return {"backups": items}

@app.get("/chat/backup/{fname}")
async def chat_backup_load(fname: str):
    """Load a single backup by filename."""
    target = _BACKUP_DIR / fname
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="backup not found")
    try:
        return _json_mod.loads(target.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"corrupt backup: {e}")

@app.delete("/chat/backup/{fname}")
async def chat_backup_delete(fname: str):
    target = _BACKUP_DIR / fname
    if target.exists():
        target.unlink()
        return {"ok": True}
    raise HTTPException(status_code=404, detail="not found")


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
