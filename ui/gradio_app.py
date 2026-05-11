"""
MaxCoder v2 Gradio UI — with Web Search + Eval tabs.
"""
import os, json, httpx, gradio as gr
from pathlib import Path

BACKEND = os.getenv("MAXCODER_BACKEND", "http://127.0.0.1:8000")

# ── Chat ──────────────────────────────────────────────────────────────────────
def chat_fn(message, history, model, use_rag, use_memory,
            use_rewriter, use_critic, use_web_search):
    msgs = []
    for u, a in history:
        msgs.append({"role": "user",      "content": u})
        if a: msgs.append({"role": "assistant", "content": a})
    msgs.append({"role": "user", "content": message})

    payload = {
        "messages": msgs, "model": model,
        "use_rag": use_rag, "use_memory": use_memory,
        "use_rewriter": use_rewriter, "use_critic": use_critic,
        "use_web_search": use_web_search,
    }
    buf = ""
    try:
        with httpx.stream("POST", f"{BACKEND}/chat",
                          json=payload, timeout=None) as r:
            for chunk in r.iter_text():
                if not chunk: continue
                buf += chunk
                yield buf
    except Exception as e:
        yield f"⚠️ Backend error: {e}\nIs `uvicorn server.app:app` running?"


# ── Memory ────────────────────────────────────────────────────────────────────
def add_memory(text, category):
    if not text.strip(): return "⚠️ Empty."
    try:
        r = httpx.post(f"{BACKEND}/memory/add",
                       json={"text": text, "category": category}, timeout=10)
        return "✅ Saved." if r.status_code == 200 else f"Error: {r.text}"
    except Exception as e: return f"⚠️ {e}"

def list_memories():
    try:
        r    = httpx.get(f"{BACKEND}/memory/list", timeout=10)
        mems = r.json().get("memories", [])
        return "\n".join(f"{i+1}. {m}" for i,m in enumerate(mems)) or "No memories yet."
    except Exception as e: return f"⚠️ {e}"

def clear_memories():
    try:
        httpx.delete(f"{BACKEND}/memory/clear", timeout=10)
        return "🗑️ Cleared."
    except Exception as e: return f"⚠️ {e}"


# ── Web search test ────────────────────────────────────────────────────────────
def manual_search(query):
    if not query.strip(): return "⚠️ Enter a query."
    try:
        r = httpx.post(f"{BACKEND}/search", json={"query": query}, timeout=30)
        d = r.json()
        return d.get("context") or "No results found."
    except Exception as e: return f"⚠️ {e}"


# ── Code runner ───────────────────────────────────────────────────────────────
def run_code(code, lang):
    if not code.strip(): return "⚠️ No code."
    try:
        r = httpx.post(f"{BACKEND}/run", json={"code": code, "lang": lang}, timeout=30)
        d = r.json()
        out = []
        if d.get("stdout"): out.append(f"**stdout:**\n```\n{d['stdout']}\n```")
        if d.get("stderr"): out.append(f"**stderr:**\n```\n{d['stderr']}\n```")
        status = "✅ exit 0" if d.get("ok") else f"❌ exit {d.get('code','?')}"
        return status + "\n\n" + "\n".join(out)
    except Exception as e: return f"⚠️ {e}"


# ── Eval ──────────────────────────────────────────────────────────────────────
def run_eval(model_choice):
    import subprocess, sys
    try:
        result = subprocess.run(
            [sys.executable, "eval/run_eval.py", "--model", model_choice],
            capture_output=True, text=True, timeout=600
        )
        output = result.stdout + result.stderr
        # Try to load latest report
        results_dir = Path("eval/results")
        reports = sorted(results_dir.glob(f"*{model_choice}*.md")) if results_dir.exists() else []
        report_text = reports[-1].read_text() if reports else ""
        return output, report_text
    except subprocess.TimeoutExpired:
        return "⏰ Eval timed out (600s).", ""
    except Exception as e:
        return f"⚠️ {e}", ""

def load_latest_report(model_choice):
    results_dir = Path("eval/results")
    if not results_dir.exists(): return "No results yet. Run an eval first."
    reports = sorted(results_dir.glob(f"*{model_choice}*.md"))
    return reports[-1].read_text() if reports else "No results for this model yet."


# ── Health ────────────────────────────────────────────────────────────────────
def check_health():
    try:
        r = httpx.get(f"{BACKEND}/health", timeout=5)
        d = r.json()
        if d.get("ok"):
            return f"🟢 Backend up | Models: {', '.join(d.get('models',[]))}"
        return f"🔴 {d.get('error')}"
    except Exception as e:
        return f"🔴 Unreachable: {e}"


# ── Build UI ──────────────────────────────────────────────────────────────────
with gr.Blocks(title="MaxCoder v2", theme=gr.themes.Soft()) as demo:

    gr.Markdown("# 🛠️ MaxCoder v2 — Local Coding LLM")
    gr.Markdown(check_health())

    # ── Chat tab ──────────────────────────────────────────────────────────────
    with gr.Tab("💬 Chat"):
        model_dd = gr.Dropdown(
            ["maxcoder-fast", "maxcoder"], value="maxcoder-fast",
            label="Model")
        with gr.Row():
            use_rag        = gr.Checkbox(value=True,  label="🔍 RAG")
            use_memory     = gr.Checkbox(value=True,  label="🧠 Memory")
            use_rewriter   = gr.Checkbox(value=True,  label="✏️ Rewriter")
            use_critic     = gr.Checkbox(value=False, label="🔄 Critic")
            use_web_search = gr.Checkbox(value=True,  label="🌐 Web Search")
        gr.ChatInterface(
            fn=chat_fn,
            additional_inputs=[
                model_dd, use_rag, use_memory,
                use_rewriter, use_critic, use_web_search
            ],
        )

    # ── Memory tab ────────────────────────────────────────────────────────────
    with gr.Tab("🧠 Memory"):
        gr.Markdown("### Teach MaxCoder your preferences")
        with gr.Row():
            mem_text = gr.Textbox(label="Memory fact", lines=2,
                placeholder='e.g. "I always use PostgreSQL"')
            mem_cat  = gr.Dropdown(
                ["general","tech_stack","style","project","constraint"],
                value="general", label="Category")
        mem_add_btn   = gr.Button("💾 Save", variant="primary")
        mem_status    = gr.Markdown()
        mem_list_btn  = gr.Button("📋 List all")
        mem_list_out  = gr.Textbox(lines=10, interactive=False)
        mem_clear_btn = gr.Button("🗑️ Clear all", variant="stop")
        mem_clear_out = gr.Markdown()
        mem_add_btn.click(add_memory,    [mem_text, mem_cat], mem_status)
        mem_list_btn.click(list_memories, [],                 mem_list_out)
        mem_clear_btn.click(clear_memories, [],               mem_clear_out)

    # ── Web Search tab ────────────────────────────────────────────────────────
    with gr.Tab("🌐 Web Search"):
        gr.Markdown("### Test web search directly")
        gr.Markdown("MaxCoder uses this automatically when it detects you need latest docs.")
        search_in  = gr.Textbox(label="Search query",
            placeholder="e.g. FastAPI latest version docs")
        search_btn = gr.Button("🔍 Search", variant="primary")
        search_out = gr.Textbox(label="Results", lines=20, interactive=False)
        search_btn.click(manual_search, [search_in], search_out)

    # ── Code Runner tab ───────────────────────────────────────────────────────
    with gr.Tab("⚡ Code Runner"):
        gr.Markdown("### Run a snippet directly (20s timeout)")
        run_lang    = gr.Dropdown(["python","javascript","bash"],
                                  value="python", label="Language")
        run_code_in = gr.Code(language="python", label="Code", lines=15)
        run_btn     = gr.Button("▶ Run", variant="primary")
        run_out     = gr.Markdown()
        run_btn.click(run_code, [run_code_in, run_lang], run_out)

    # ── Eval tab ──────────────────────────────────────────────────────────────
    with gr.Tab("📊 Eval"):
        gr.Markdown("### Benchmark MaxCoder quality")
        gr.Markdown(
            "Runs all prompts in `eval/prompts.jsonl`, scores on 5 dimensions, "
            "saves a Markdown report to `eval/results/`."
        )
        eval_model = gr.Dropdown(
            ["maxcoder-fast", "maxcoder"], value="maxcoder-fast",
            label="Model to evaluate")
        eval_btn    = gr.Button("▶ Run Eval (takes 5-15 min)", variant="primary")
        eval_log    = gr.Textbox(label="Progress log", lines=15, interactive=False)
        eval_report = gr.Markdown(label="Report")
        load_btn    = gr.Button("📄 Load latest report")

        eval_btn.click(run_eval,          [eval_model], [eval_log, eval_report])
        load_btn.click(load_latest_report,[eval_model], eval_report)

    # ── Status tab ────────────────────────────────────────────────────────────
    with gr.Tab("ℹ️ Status"):
        refresh_btn = gr.Button("🔄 Refresh")
        status_out  = gr.Markdown(check_health())
        refresh_btn.click(check_health, [], status_out)

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, show_error=True)
