"""
MaxCoder v2 — Redesigned UI
- Font Awesome icons (no emojis)
- Inline code execution after generation
- Minimalistic dark-accent design
- Auto-run toggle
"""
import os, re, json, httpx, gradio as gr

BACKEND = os.getenv("MAXCODER_BACKEND", "http://127.0.0.1:8000")

# ── Helpers ───────────────────────────────────────────────────────────────────
def extract_first_code_block(text: str) -> tuple[str, str]:
    """Return (lang, code) of the first fenced block, or ('', '')."""
    m = re.search(r"```(\w*)[^\n]*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).lower() or "python", m.group(2).strip()
    return "", ""

def run_code_block(code: str, lang: str) -> str:
    if not code.strip():
        return ""
    supported = ["python", "javascript", "bash"]
    if lang not in supported:
        lang = "python"
    try:
        r = httpx.post(f"{BACKEND}/run",
                       json={"code": code, "lang": lang}, timeout=30)
        d = r.json()
        out_parts = []
        if d.get("stdout"):
            out_parts.append(f"<pre class='out-stdout'>{d['stdout'].strip()}</pre>")
        if d.get("stderr"):
            out_parts.append(f"<pre class='out-stderr'>{d['stderr'].strip()}</pre>")
        status_cls = "badge-ok" if d.get("ok") else "badge-err"
        status_txt = "exit 0" if d.get("ok") else f"exit {d.get('code','?')}"
        badge = f"<span class='{status_cls}'>{status_txt}</span>"
        return badge + "".join(out_parts) if out_parts else badge
    except Exception as e:
        return f"<pre class='out-stderr'>Backend error: {e}</pre>"

# ── Chat fn ───────────────────────────────────────────────────────────────────
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
        yield f"Backend error: {e}\nIs `uvicorn server.app:app` running?"

def chat_and_run(message, history, model, use_rag, use_memory,
                 use_rewriter, use_critic, use_web_search, auto_run):
    """Stream chat response then auto-execute the first code block."""
    final = ""
    for partial in chat_fn(message, history, model, use_rag,
                           use_memory, use_rewriter, use_critic, use_web_search):
        final = partial
        yield partial, gr.update(visible=False), "", "", ""

    if auto_run and final:
        lang, code = extract_first_code_block(final)
        if code:
            result_html = run_code_block(code, lang)
            yield (final,
                   gr.update(visible=True),
                   code,
                   lang or "python",
                   result_html)
        else:
            yield final, gr.update(visible=False), "", "", ""
    else:
        yield final, gr.update(visible=False), "", "", ""

# ── Memory ────────────────────────────────────────────────────────────────────
def add_memory(text, category):
    if not text.strip(): return "<span class='badge-err'>Empty text</span>"
    try:
        r = httpx.post(f"{BACKEND}/memory/add",
                       json={"text": text, "category": category}, timeout=10)
        return "<span class='badge-ok'>Saved</span>" if r.status_code == 200 else f"Error: {r.text}"
    except Exception as e: return f"Error: {e}"

def list_memories():
    try:
        r = httpx.get(f"{BACKEND}/memory/list", timeout=10)
        mems = r.json().get("memories", [])
        if not mems: return "No memories stored yet."
        return "\n".join(f"{i+1}. {m}" for i,m in enumerate(mems))
    except Exception as e: return f"Error: {e}"

def clear_memories():
    try:
        httpx.delete(f"{BACKEND}/memory/clear", timeout=10)
        return "<span class='badge-ok'>Cleared</span>"
    except Exception as e: return f"Error: {e}"

# ── Web search ────────────────────────────────────────────────────────────────
def manual_search(query):
    if not query.strip(): return "Enter a query."
    try:
        r = httpx.post(f"{BACKEND}/search", json={"query": query}, timeout=30)
        return r.json().get("context") or "No results found."
    except Exception as e: return f"Error: {e}"

# ── Code runner ───────────────────────────────────────────────────────────────
def run_code_manual(code, lang):
    if not code.strip(): return "<span class='badge-err'>No code entered</span>"
    return run_code_block(code, lang)

# ── Eval ──────────────────────────────────────────────────────────────────────
def run_eval(model_choice):
    import subprocess, sys
    try:
        result = subprocess.run(
            [sys.executable, "eval/run_eval.py", "--model", model_choice],
            capture_output=True, text=True, timeout=600)
        output = result.stdout + result.stderr
        from pathlib import Path
        results_dir = Path("eval/results")
        reports = sorted(results_dir.glob(f"*{model_choice}*.md")) if results_dir.exists() else []
        report_text = reports[-1].read_text() if reports else ""
        return output, report_text
    except subprocess.TimeoutExpired:
        return "Eval timed out (600s).", ""
    except Exception as e:
        return f"Error: {e}", ""

def load_latest_report(model_choice):
    from pathlib import Path
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
            models = ", ".join(d.get("models", []))
            return f'<span class="badge-ok">Online</span> &nbsp; Models: <code>{models}</code>'
        return f'<span class="badge-err">Offline</span> {d.get("error","")}'
    except Exception as e:
        return f'<span class="badge-err">Unreachable</span> {e}'

# ── CSS ───────────────────────────────────────────────────────────────────────
CSS = """
/* ── Font Awesome ── */
@import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css');

/* ── Root palette ── */
:root {
    --bg:        #0f1117;
    --surface:   #1a1d27;
    --surface2:  #22263a;
    --border:    #2e3250;
    --accent:    #5b6af0;
    --accent2:   #7c8aff;
    --ok:        #22c55e;
    --err:       #ef4444;
    --warn:      #f59e0b;
    --text:      #e2e8f0;
    --muted:     #94a3b8;
    --radius:    10px;
    --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
}

/* ── Global ── */
body, .gradio-container {
    background: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'Inter', system-ui, sans-serif !important;
}

/* ── Header ── */
.mc-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 20px 0 10px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 16px;
}
.mc-header .mc-logo {
    width: 38px; height: 38px;
    background: var(--accent);
    border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px; color: #fff;
}
.mc-header h1 {
    font-size: 1.4rem; font-weight: 700;
    color: var(--text) !important;
    margin: 0;
}
.mc-header .mc-version {
    font-size: 0.75rem; color: var(--muted);
    background: var(--surface2);
    padding: 2px 8px; border-radius: 20px;
}

/* ── Tabs ── */
.tab-nav button {
    background: transparent !important;
    color: var(--muted) !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    border-radius: 0 !important;
    font-size: 0.85rem !important;
    padding: 8px 16px !important;
    transition: all 0.2s;
}
.tab-nav button.selected {
    color: var(--accent2) !important;
    border-bottom-color: var(--accent2) !important;
}
.tab-nav button:hover { color: var(--text) !important; }

/* ── Panels / cards ── */
.mc-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px;
    margin-bottom: 12px;
}

/* ── Inputs ── */
input, textarea, select,
.gradio-textbox textarea,
.gradio-textbox input {
    background: var(--surface2) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: var(--radius) !important;
    font-family: inherit !important;
}
input:focus, textarea:focus {
    border-color: var(--accent) !important;
    outline: none !important;
    box-shadow: 0 0 0 2px rgba(91,106,240,0.2) !important;
}

/* ── Buttons ── */
button.primary, .gr-button-primary {
    background: var(--accent) !important;
    color: #fff !important;
    border: none !important;
    border-radius: var(--radius) !important;
    font-weight: 600 !important;
    transition: background 0.2s !important;
}
button.primary:hover { background: var(--accent2) !important; }
button.secondary, .gr-button-secondary {
    background: var(--surface2) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
}
button.stop, .gr-button-stop {
    background: var(--err) !important;
    color: #fff !important;
    border: none !important;
    border-radius: var(--radius) !important;
}

/* ── Chatbot ── */
.chatbot {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
}
.chatbot .message.user {
    background: var(--accent) !important;
    color: #fff !important;
    border-radius: 18px 18px 4px 18px !important;
}
.chatbot .message.bot {
    background: var(--surface2) !important;
    color: var(--text) !important;
    border-radius: 18px 18px 18px 4px !important;
    border: 1px solid var(--border) !important;
}
/* Code blocks inside chat */
.chatbot pre, .chatbot code {
    background: var(--bg) !important;
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    font-family: var(--font-mono) !important;
    font-size: 0.82rem !important;
}

/* ── Options bar ── */
.options-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    padding: 8px 12px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    margin-bottom: 8px;
}
.options-bar label {
    display: flex;
    align-items: center;
    gap: 5px;
    font-size: 0.8rem;
    color: var(--muted);
    cursor: pointer;
    user-select: none;
}
.options-bar label:hover { color: var(--text); }

/* ── Inline code output ── */
.code-output-panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 16px;
    margin-top: 8px;
}
.code-output-panel h4 {
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 0 0 8px;
}
pre.out-stdout {
    background: #0a1628 !important;
    color: #86efac !important;
    border-left: 3px solid var(--ok) !important;
    padding: 10px 14px !important;
    border-radius: 6px !important;
    font-family: var(--font-mono) !important;
    font-size: 0.82rem !important;
    white-space: pre-wrap;
    margin: 0;
}
pre.out-stderr {
    background: #1f0a0a !important;
    color: #fca5a5 !important;
    border-left: 3px solid var(--err) !important;
    padding: 10px 14px !important;
    border-radius: 6px !important;
    font-family: var(--font-mono) !important;
    font-size: 0.82rem !important;
    white-space: pre-wrap;
    margin: 0;
}

/* ── Badges ── */
.badge-ok {
    display: inline-block;
    background: rgba(34,197,94,0.15);
    color: var(--ok);
    border: 1px solid rgba(34,197,94,0.3);
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    margin-bottom: 6px;
}
.badge-err {
    display: inline-block;
    background: rgba(239,68,68,0.15);
    color: var(--err);
    border: 1px solid rgba(239,68,68,0.3);
    padding: 2px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    margin-bottom: 6px;
}

/* ── Dropdowns ── */
.gradio-dropdown select, .gradio-dropdown div {
    background: var(--surface2) !important;
    border-color: var(--border) !important;
    color: var(--text) !important;
}

/* ── Checkboxes ── */
input[type=checkbox] { accent-color: var(--accent); }

/* ── Code editor ── */
.code-editor, .cm-editor {
    background: var(--bg) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius) !important;
    font-family: var(--font-mono) !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover { background: var(--accent); }

/* ── Section labels ── */
.section-label {
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--muted);
    margin-bottom: 6px;
}

/* ── Status dot ── */
.status-line {
    font-size: 0.8rem;
    color: var(--muted);
    padding: 4px 0;
}

/* ── Memory list ── */
.memory-list {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 10px 14px;
    font-size: 0.83rem;
    line-height: 1.8;
    min-height: 80px;
}

/* ── Eval score bar ── */
.eval-bar {
    height: 6px;
    background: var(--accent);
    border-radius: 3px;
    margin-top: 4px;
}
"""

# ── Header HTML ──────────────────────────────────────────────────────────────
HEADER_HTML = """
<link rel="stylesheet"
 href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css"/>
<div class="mc-header">
  <div class="mc-logo"><i class="fa-solid fa-code"></i></div>
  <h1>MaxCoder</h1>
  <span class="mc-version">v2.1</span>
</div>
"""

# ── Build UI ──────────────────────────────────────────────────────────────────
with gr.Blocks(title="MaxCoder", theme=gr.themes.Base(), css=CSS) as demo:

    gr.HTML(HEADER_HTML)

    # Status bar
    status_html = gr.HTML(f'<div class="status-line">{check_health()}</div>')

    # ── Chat Tab ──────────────────────────────────────────────────────────────
    with gr.Tab("<i class='fa fa-message'></i>  Chat"):

        # Options bar
        with gr.Row(elem_classes="options-bar"):
            model_dd = gr.Dropdown(
                choices=["maxcoder-fast", "maxcoder"],
                value="maxcoder-fast",
                label="Model",
                scale=2,
                min_width=180,
            )
            use_web = gr.Checkbox(value=True,  label="<i class='fa fa-globe'></i> Web Search")
            use_rag = gr.Checkbox(value=True,  label="<i class='fa fa-database'></i> RAG")
            use_mem = gr.Checkbox(value=True,  label="<i class='fa fa-brain'></i> Memory")
            use_rew = gr.Checkbox(value=True,  label="<i class='fa fa-pen'></i> Rewriter")
            use_cri = gr.Checkbox(value=False, label="<i class='fa fa-magnifying-glass'></i> Critic")
            auto_run= gr.Checkbox(value=True,  label="<i class='fa fa-play'></i> Auto-run code")

        # Chat interface
        chatbot = gr.Chatbot(
            height=460,
            show_label=False,
            render_markdown=True,
            bubble_full_width=False,
        )
        with gr.Row():
            msg_box = gr.Textbox(
                placeholder="Ask MaxCoder to build anything...",
                show_label=False,
                scale=9,
                lines=1,
            )
            send_btn = gr.Button(
                "<i class='fa fa-paper-plane'></i>",
                variant="primary",
                scale=1,
                min_width=60,
            )

        # Inline output panel (hidden until code runs)
        with gr.Column(visible=False, elem_classes="code-output-panel") as output_panel:
            gr.HTML("<h4><i class='fa fa-terminal'></i> &nbsp;Code Output</h4>")
            output_code = gr.Code(label="Extracted code", lines=8, interactive=True)
            output_lang = gr.Dropdown(
                ["python","javascript","bash"],
                value="python", label="Language", scale=1)
            rerun_btn   = gr.Button(
                "<i class='fa fa-rotate-right'></i>  Re-run",
                variant="secondary", scale=1)
            output_html = gr.HTML()

        # Wire chat
        def user_submit(msg, history):
            return "", history + [[msg, None]]

        def bot_respond(history, model, use_rag, use_mem, use_rew,
                        use_cri, use_web, auto_run):
            user_msg = history[-1][0]
            history[-1][1] = ""
            full = ""
            for partial in chat_fn(user_msg, history[:-1], model,
                                   use_rag, use_mem, use_rew, use_cri, use_web):
                history[-1][1] = partial
                full = partial
                yield history, gr.update(visible=False), "", "python", ""

            if auto_run and full:
                lang, code = extract_first_code_block(full)
                if code:
                    result_html = run_code_block(code, lang or "python")
                    yield (history,
                           gr.update(visible=True),
                           code,
                           lang or "python",
                           result_html)

        send_btn.click(
            user_submit, [msg_box, chatbot], [msg_box, chatbot]
        ).then(
            bot_respond,
            [chatbot, model_dd, use_rag, use_mem, use_rew,
             use_cri, use_web, auto_run],
            [chatbot, output_panel, output_code, output_lang, output_html]
        )
        msg_box.submit(
            user_submit, [msg_box, chatbot], [msg_box, chatbot]
        ).then(
            bot_respond,
            [chatbot, model_dd, use_rag, use_mem, use_rew,
             use_cri, use_web, auto_run],
            [chatbot, output_panel, output_code, output_lang, output_html]
        )
        rerun_btn.click(
            lambda code, lang: run_code_block(code, lang),
            [output_code, output_lang], output_html
        )

    # ── Memory Tab ────────────────────────────────────────────────────────────
    with gr.Tab("<i class='fa fa-brain'></i>  Memory"):
        gr.HTML("<p style='color:var(--muted);font-size:0.85rem;margin-bottom:12px'>"
                "<i class='fa fa-circle-info'></i> &nbsp;"
                "Teach MaxCoder your preferences. These are injected into every prompt.</p>")
        with gr.Row():
            mem_text = gr.Textbox(
                label="Memory fact",
                placeholder='e.g. "I always use PostgreSQL" or "I prefer pnpm"',
                lines=2, scale=4)
            mem_cat = gr.Dropdown(
                ["general","tech_stack","style","project","constraint"],
                value="general", label="Category", scale=1)
        with gr.Row():
            mem_save_btn  = gr.Button(
                "<i class='fa fa-floppy-disk'></i>  Save", variant="primary")
            mem_list_btn  = gr.Button(
                "<i class='fa fa-list'></i>  List all", variant="secondary")
            mem_clear_btn = gr.Button(
                "<i class='fa fa-trash'></i>  Clear all", variant="stop")
        mem_status   = gr.HTML()
        mem_list_out = gr.Textbox(
            label="Stored memories", lines=10,
            interactive=False, elem_classes="memory-list")

        mem_save_btn.click(add_memory,    [mem_text, mem_cat], mem_status)
        mem_list_btn.click(list_memories, [],                  mem_list_out)
        mem_clear_btn.click(clear_memories, [],                mem_status)

    # ── Web Search Tab ────────────────────────────────────────────────────────
    with gr.Tab("<i class='fa fa-globe'></i>  Web Search"):
        gr.HTML("<p style='color:var(--muted);font-size:0.85rem;margin-bottom:12px'>"
                "<i class='fa fa-circle-info'></i> &nbsp;"
                "Test the web search directly. MaxCoder uses this automatically in chat.</p>")
        with gr.Row():
            search_in  = gr.Textbox(
                placeholder="e.g. FastAPI 0.115 release notes",
                label="Search query", scale=5)
            search_btn = gr.Button(
                "<i class='fa fa-magnifying-glass'></i>  Search",
                variant="primary", scale=1)
        search_out = gr.Textbox(
            label="Raw search context (what gets injected into the prompt)",
            lines=22, interactive=False)
        search_btn.click(manual_search, [search_in], search_out)
        search_in.submit(manual_search, [search_in], search_out)

    # ── Code Runner Tab ───────────────────────────────────────────────────────
    with gr.Tab("<i class='fa fa-terminal'></i>  Runner"):
        gr.HTML("<p style='color:var(--muted);font-size:0.85rem;margin-bottom:12px'>"
                "<i class='fa fa-circle-info'></i> &nbsp;"
                "Paste and run any snippet manually. 20s timeout.</p>")
        with gr.Row():
            run_lang = gr.Dropdown(
                ["python","javascript","bash"],
                value="python", label="Language", scale=1, min_width=140)
            run_btn  = gr.Button(
                "<i class='fa fa-play'></i>  Run",
                variant="primary", scale=1, min_width=100)
        run_code_in = gr.Code(language="python", label="Code", lines=18)
        run_out_html = gr.HTML()

        def update_lang(lang):
            return gr.update(language=lang)

        run_lang.change(update_lang, [run_lang], run_code_in)
        run_btn.click(run_code_manual, [run_code_in, run_lang], run_out_html)

    # ── Eval Tab ──────────────────────────────────────────────────────────────
    with gr.Tab("<i class='fa fa-chart-bar'></i>  Eval"):
        gr.HTML("<p style='color:var(--muted);font-size:0.85rem;margin-bottom:12px'>"
                "<i class='fa fa-circle-info'></i> &nbsp;"
                "Benchmark model quality across correctness, completeness, "
                "code quality and CoT structure. Run before and after fine-tuning "
                "to track improvement.</p>")
        with gr.Row():
            eval_model = gr.Dropdown(
                ["maxcoder-fast","maxcoder"],
                value="maxcoder-fast", label="Model", scale=2)
            eval_run_btn  = gr.Button(
                "<i class='fa fa-play'></i>  Run Benchmark",
                variant="primary", scale=1)
            eval_load_btn = gr.Button(
                "<i class='fa fa-file-lines'></i>  Load Latest Report",
                variant="secondary", scale=1)
        eval_log    = gr.Textbox(
            label="<i class='fa fa-terminal'></i> Progress",
            lines=10, interactive=False)
        eval_report = gr.Markdown(label="Report")

        eval_run_btn.click(run_eval,           [eval_model], [eval_log, eval_report])
        eval_load_btn.click(load_latest_report,[eval_model],  eval_report)

    # ── Status Tab ────────────────────────────────────────────────────────────
    with gr.Tab("<i class='fa fa-circle-dot'></i>  Status"):
        refresh_btn = gr.Button(
            "<i class='fa fa-rotate-right'></i>  Refresh",
            variant="secondary")
        status_detail = gr.HTML(check_health())
        refresh_btn.click(check_health, [], status_detail)

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860,
                show_error=True, favicon_path=None)
