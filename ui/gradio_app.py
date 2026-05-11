"""
MaxCoder v2.1 — Clean UI
Font Awesome icons via JS injection, clean dark theme, inline code execution.
"""
import os, re, httpx, gradio as gr

BACKEND = os.getenv("MAXCODER_BACKEND", "http://127.0.0.1:8000")

# ── Helpers ───────────────────────────────────────────────────────────────────
def extract_first_code_block(text: str) -> tuple[str, str]:
    m = re.search(r"```(\w*)[^\n]*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).lower() or "python", m.group(2).strip()
    return "", ""

def run_code_block(code: str, lang: str) -> str:
    if not code.strip():
        return ""
    if lang not in ["python", "javascript", "bash"]:
        lang = "python"
    try:
        r = httpx.post(f"{BACKEND}/run",
                       json={"code": code, "lang": lang}, timeout=30)
        d = r.json()
        parts = []
        if d.get("stdout"):
            parts.append(
                f"<pre style='background:#0a1628;color:#86efac;"
                f"border-left:3px solid #22c55e;padding:10px 14px;"
                f"border-radius:6px;font-family:monospace;font-size:0.82rem;"
                f"white-space:pre-wrap;margin:4px 0'>{d['stdout'].strip()}</pre>"
            )
        if d.get("stderr"):
            parts.append(
                f"<pre style='background:#1f0a0a;color:#fca5a5;"
                f"border-left:3px solid #ef4444;padding:10px 14px;"
                f"border-radius:6px;font-family:monospace;font-size:0.82rem;"
                f"white-space:pre-wrap;margin:4px 0'>{d['stderr'].strip()}</pre>"
            )
        ok    = d.get("ok", False)
        badge_bg  = "rgba(34,197,94,0.15)"  if ok else "rgba(239,68,68,0.15)"
        badge_col = "#22c55e"               if ok else "#ef4444"
        badge_brd = "rgba(34,197,94,0.35)"  if ok else "rgba(239,68,68,0.35)"
        badge_txt = "exit 0"                if ok else f"exit {d.get('code','?')}"
        badge = (
            f"<span style='display:inline-block;background:{badge_bg};"
            f"color:{badge_col};border:1px solid {badge_brd};"
            f"padding:2px 12px;border-radius:20px;font-size:0.75rem;"
            f"font-weight:600;margin-bottom:6px'>"
            f"<i class='fa-solid fa-circle-{'check' if ok else 'xmark'}'></i>"
            f"&nbsp;{badge_txt}</span>"
        )
        return badge + "".join(parts)
    except Exception as e:
        return f"<pre style='color:#fca5a5'>Error: {e}</pre>"

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
        yield f"Backend error: {e}\nIs `uvicorn server.app:app` running?"

# ── Memory ────────────────────────────────────────────────────────────────────
def add_memory(text, category):
    if not text.strip():
        return _badge("Empty text", ok=False)
    try:
        r = httpx.post(f"{BACKEND}/memory/add",
                       json={"text": text, "category": category}, timeout=10)
        return _badge("Saved") if r.status_code == 200 else _badge(r.text, ok=False)
    except Exception as e:
        return _badge(str(e), ok=False)

def list_memories():
    try:
        r    = httpx.get(f"{BACKEND}/memory/list", timeout=10)
        mems = r.json().get("memories", [])
        if not mems: return "No memories stored yet."
        return "\n".join(f"{i+1}. {m}" for i, m in enumerate(mems))
    except Exception as e:
        return f"Error: {e}"

def clear_memories():
    try:
        httpx.delete(f"{BACKEND}/memory/clear", timeout=10)
        return _badge("Cleared")
    except Exception as e:
        return _badge(str(e), ok=False)

def _badge(text: str, ok: bool = True) -> str:
    bg  = "rgba(34,197,94,0.15)"  if ok else "rgba(239,68,68,0.15)"
    col = "#22c55e"               if ok else "#ef4444"
    brd = "rgba(34,197,94,0.35)"  if ok else "rgba(239,68,68,0.35)"
    ico = "circle-check"          if ok else "circle-xmark"
    return (
        f"<span style='display:inline-block;background:{bg};color:{col};"
        f"border:1px solid {brd};padding:3px 12px;border-radius:20px;"
        f"font-size:0.78rem;font-weight:600'>"
        f"<i class='fa-solid fa-{ico}'></i>&nbsp;{text}</span>"
    )

# ── Web search ────────────────────────────────────────────────────────────────
def manual_search(query):
    if not query.strip(): return "Enter a query."
    try:
        r = httpx.post(f"{BACKEND}/search", json={"query": query}, timeout=30)
        return r.json().get("context") or "No results found."
    except Exception as e:
        return f"Error: {e}"

# ── Code runner ───────────────────────────────────────────────────────────────
def run_code_manual(code, lang):
    if not code.strip():
        return _badge("No code entered", ok=False)
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
        rd = Path("eval/results")
        reports = sorted(rd.glob(f"*{model_choice}*.md")) if rd.exists() else []
        report  = reports[-1].read_text() if reports else ""
        return output, report
    except subprocess.TimeoutExpired:
        return "Eval timed out (600s).", ""
    except Exception as e:
        return f"Error: {e}", ""

def load_latest_report(model_choice):
    from pathlib import Path
    rd = Path("eval/results")
    if not rd.exists(): return "No results yet. Run an eval first."
    reports = sorted(rd.glob(f"*{model_choice}*.md"))
    return reports[-1].read_text() if reports else "No results for this model yet."

# ── Health ────────────────────────────────────────────────────────────────────
def check_health():
    try:
        r = httpx.get(f"{BACKEND}/health", timeout=5)
        d = r.json()
        if d.get("ok"):
            models = ", ".join(d.get("models", []))
            return (
                "<span style='display:inline-flex;align-items:center;gap:6px;"
                "background:rgba(34,197,94,0.12);color:#22c55e;"
                "border:1px solid rgba(34,197,94,0.3);padding:3px 12px;"
                "border-radius:20px;font-size:0.78rem;font-weight:600'>"
                "<i class='fa-solid fa-circle' style='font-size:7px'></i> Online"
                f"</span>&nbsp;&nbsp;<span style='color:#94a3b8;font-size:0.8rem'>"
                f"Models: <code style='color:#7c8aff'>{models}</code></span>"
            )
        return _badge(d.get("error", "Offline"), ok=False)
    except Exception as e:
        return _badge(f"Unreachable: {e}", ok=False)

# ── CSS ───────────────────────────────────────────────────────────────────────
CSS = """
:root {
    --bg:       #0f1117;
    --s1:       #1a1d27;
    --s2:       #22263a;
    --border:   #2e3250;
    --accent:   #5b6af0;
    --accent2:  #7c8aff;
    --ok:       #22c55e;
    --err:      #ef4444;
    --text:     #e2e8f0;
    --muted:    #94a3b8;
    --r:        10px;
    --mono:     'JetBrains Mono','Fira Code',monospace;
}

/* Base */
body, .gradio-container, .main {
    background: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'Inter',system-ui,sans-serif !important;
}
.gradio-container { max-width: 1200px !important; margin: 0 auto !important; }

/* Tabs */
.tab-nav { border-bottom: 1px solid var(--border) !important; }
.tab-nav > button {
    background: transparent !important;
    color: var(--muted) !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    border-radius: 0 !important;
    font-size: 0.84rem !important;
    font-weight: 500 !important;
    padding: 10px 18px !important;
    transition: all 0.18s !important;
}
.tab-nav > button.selected {
    color: var(--accent2) !important;
    border-bottom-color: var(--accent2) !important;
}
.tab-nav > button:hover { color: var(--text) !important; }

/* Inputs */
input[type=text], textarea,
.gradio-textbox textarea,
.gradio-textbox input {
    background: var(--s2) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: var(--r) !important;
    font-size: 0.9rem !important;
}
input[type=text]:focus, textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(91,106,240,0.18) !important;
    outline: none !important;
}

/* Buttons */
.gr-button, button {
    border-radius: var(--r) !important;
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    transition: all 0.18s !important;
}
.gr-button-primary, button.primary {
    background: var(--accent) !important;
    color: #fff !important;
    border: none !important;
}
.gr-button-primary:hover, button.primary:hover {
    background: var(--accent2) !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(91,106,240,0.35) !important;
}
.gr-button-secondary, button.secondary {
    background: var(--s2) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
}
.gr-button-secondary:hover, button.secondary:hover {
    border-color: var(--accent) !important;
    color: var(--accent2) !important;
}
button.stop {
    background: rgba(239,68,68,0.15) !important;
    color: var(--err) !important;
    border: 1px solid rgba(239,68,68,0.3) !important;
}

/* Chatbot */
.chatbot, div[data-testid='chatbot'] {
    background: var(--s1) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r) !important;
}
.chatbot .message-wrap .message {
    border-radius: 14px !important;
    font-size: 0.9rem !important;
    line-height: 1.65 !important;
}
/* user bubble */
.chatbot .message-wrap .message.user {
    background: var(--accent) !important;
    color: #fff !important;
}
/* bot bubble */
.chatbot .message-wrap .message.bot {
    background: var(--s2) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
}
/* code inside chat */
.chatbot pre {
    background: var(--bg) !important;
    border: 1px solid var(--border) !important;
    border-radius: 7px !important;
    padding: 12px !important;
    font-family: var(--mono) !important;
    font-size: 0.81rem !important;
    overflow-x: auto;
}
.chatbot code {
    font-family: var(--mono) !important;
    font-size: 0.82rem !important;
    color: var(--accent2) !important;
}

/* Options row */
.options-row {
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 6px !important;
    align-items: center !important;
    background: var(--s1) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r) !important;
    padding: 8px 14px !important;
    margin-bottom: 8px !important;
}
/* Checkboxes */
input[type=checkbox] { accent-color: var(--accent) !important; }
.gradio-checkbox label,
.gradio-checkbox span {
    color: var(--muted) !important;
    font-size: 0.82rem !important;
}
.gradio-checkbox:hover span { color: var(--text) !important; }

/* Dropdown */
.gradio-dropdown > div {
    background: var(--s2) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r) !important;
    color: var(--text) !important;
}
.gradio-dropdown select {
    background: var(--s2) !important;
    color: var(--text) !important;
}

/* Labels */
label > span, .block > label > span {
    color: var(--muted) !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
}

/* Code editor */
.cm-editor, .cm-scroller {
    background: var(--bg) !important;
    font-family: var(--mono) !important;
    font-size: 0.83rem !important;
}
.cm-gutters { background: var(--s1) !important; border-right-color: var(--border) !important; }

/* Textbox */
.gradio-textbox {
    background: var(--s2) !important;
    border-color: var(--border) !important;
    border-radius: var(--r) !important;
}

/* Scrollbar */
::-webkit-scrollbar { width: 5px; height: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--accent); }

/* Output panel */
.output-panel {
    background: var(--s1);
    border: 1px solid var(--border);
    border-radius: var(--r);
    padding: 14px 16px;
    margin-top: 10px;
}
.output-panel-title {
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    gap: 6px;
}

/* Markdown */
.gradio-markdown, .prose {
    color: var(--text) !important;
}
.gradio-markdown h1,.gradio-markdown h2,.gradio-markdown h3 {
    color: var(--text) !important;
}
.gradio-markdown code {
    background: var(--s2) !important;
    color: var(--accent2) !important;
    padding: 1px 6px;
    border-radius: 4px;
    font-family: var(--mono) !important;
}
.gradio-markdown a { color: var(--accent2) !important; }

/* Info text */
.info-text {
    color: var(--muted);
    font-size: 0.83rem;
    padding: 6px 0 12px;
    display: flex;
    align-items: center;
    gap: 6px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 14px;
}
"""

# ── FA + Inter fonts injection ─────────────────────────────────────────────────
HEAD_HTML = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet"
  href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
<link rel="stylesheet"
  href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css">
"""

LOGO_HTML = """
<div style="display:flex;align-items:center;gap:12px;
            padding:18px 0 12px;border-bottom:1px solid #2e3250;
            margin-bottom:14px">
  <div style="width:40px;height:40px;background:#5b6af0;border-radius:10px;
              display:flex;align-items:center;justify-content:center;
              font-size:18px;color:#fff">
    <i class="fa-solid fa-code"></i>
  </div>
  <div>
    <div style="font-size:1.3rem;font-weight:700;color:#e2e8f0;line-height:1">
      MaxCoder
    </div>
    <div style="font-size:0.72rem;color:#94a3b8;margin-top:2px">
      Local coding LLM &nbsp;&middot;&nbsp; Qwen2.5-Coder
    </div>
  </div>
  <span style="margin-left:8px;font-size:0.7rem;color:#7c8aff;
               background:#22263a;padding:2px 9px;border-radius:20px;
               border:1px solid #2e3250">v2.1</span>
</div>
"""

# ── Build UI ──────────────────────────────────────────────────────────────────
with gr.Blocks(title="MaxCoder", theme=gr.themes.Base(), css=CSS,
               head=HEAD_HTML) as demo:

    gr.HTML(LOGO_HTML)
    status_bar = gr.HTML(check_health())

    # ══ Chat ══════════════════════════════════════════════════════════════════
    with gr.Tab("Chat"):
        # Options
        with gr.Row(elem_classes="options-row"):
            model_dd   = gr.Dropdown(
                ["maxcoder-fast","maxcoder"],
                value="maxcoder-fast", label="Model",
                scale=2, min_width=170)
            use_web    = gr.Checkbox(value=True,  label="Web Search", scale=1)
            use_rag    = gr.Checkbox(value=True,  label="RAG",        scale=1)
            use_mem    = gr.Checkbox(value=True,  label="Memory",     scale=1)
            use_rew    = gr.Checkbox(value=True,  label="Rewriter",   scale=1)
            use_cri    = gr.Checkbox(value=False, label="Critic",     scale=1)
            auto_run   = gr.Checkbox(value=True,  label="Auto-run",   scale=1)

        # Chatbot
        chatbot = gr.Chatbot(
            height=440,
            show_label=False,
            render_markdown=True,
            bubble_full_width=False,
            avatar_images=(None, None),
        )

        # Input row
        with gr.Row():
            msg_box = gr.Textbox(
                placeholder="Ask MaxCoder to build anything...",
                show_label=False, scale=9, lines=1,
                container=False)
            send_btn = gr.Button(
                "Send", variant="primary", scale=1, min_width=80)

        # Inline output panel
        with gr.Column(visible=False) as output_panel:
            gr.HTML(
                "<div class='output-panel-title'>"
                "<i class='fa-solid fa-terminal'></i> Code Output</div>"
            )
            with gr.Row():
                output_lang = gr.Dropdown(
                    ["python","javascript","bash"],
                    value="python", label="Language",
                    scale=1, min_width=130)
                rerun_btn = gr.Button(
                    "Re-run", variant="secondary",
                    scale=1, min_width=100)
            output_code = gr.Code(
                label="Extracted code", lines=8, interactive=True)
            output_html = gr.HTML()

        # ── Wire up chat ──────────────────────────────────────────────────────
        def user_msg(msg, hist):
            return "", hist + [[msg, None]]

        def bot_reply(hist, model, rag, mem, rew, cri, web, arun):
            user_msg_text = hist[-1][0]
            hist[-1][1]   = ""
            full = ""

            for partial in chat_fn(
                user_msg_text, hist[:-1],
                model, rag, mem, rew, cri, web
            ):
                hist[-1][1] = partial
                full = partial
                yield hist, gr.update(visible=False), "", "python", ""

            if arun and full:
                lang, code = extract_first_code_block(full)
                if code:
                    html = run_code_block(code, lang or "python")
                    yield (hist,
                           gr.update(visible=True),
                           code,
                           lang or "python",
                           html)

        send_btn.click(
            user_msg, [msg_box, chatbot], [msg_box, chatbot]
        ).then(
            bot_reply,
            [chatbot, model_dd, use_rag, use_mem, use_rew,
             use_cri, use_web, auto_run],
            [chatbot, output_panel, output_code, output_lang, output_html]
        )
        msg_box.submit(
            user_msg, [msg_box, chatbot], [msg_box, chatbot]
        ).then(
            bot_reply,
            [chatbot, model_dd, use_rag, use_mem, use_rew,
             use_cri, use_web, auto_run],
            [chatbot, output_panel, output_code, output_lang, output_html]
        )
        rerun_btn.click(
            lambda c, l: run_code_block(c, l),
            [output_code, output_lang], output_html
        )

    # ══ Memory ════════════════════════════════════════════════════════════════
    with gr.Tab("Memory"):
        gr.HTML(
            "<div class='info-text'>"
            "<i class='fa-solid fa-circle-info'></i>"
            "Teach MaxCoder your preferences — injected into every prompt."
            "</div>"
        )
        with gr.Row():
            mem_text = gr.Textbox(
                label="Memory fact",
                placeholder='e.g. "I always use PostgreSQL"',
                lines=2, scale=4)
            mem_cat = gr.Dropdown(
                ["general","tech_stack","style","project","constraint"],
                value="general", label="Category", scale=1)
        with gr.Row():
            mem_save_btn  = gr.Button("Save",      variant="primary",   scale=1)
            mem_list_btn  = gr.Button("List all",  variant="secondary", scale=1)
            mem_clear_btn = gr.Button("Clear all", variant="stop",      scale=1)
        mem_status   = gr.HTML()
        mem_list_out = gr.Textbox(
            label="Stored memories", lines=10, interactive=False)

        mem_save_btn.click(add_memory,     [mem_text, mem_cat], mem_status)
        mem_list_btn.click(list_memories,  [],                  mem_list_out)
        mem_clear_btn.click(clear_memories,[],                  mem_status)

    # ══ Web Search ════════════════════════════════════════════════════════════
    with gr.Tab("Web Search"):
        gr.HTML(
            "<div class='info-text'>"
            "<i class='fa-solid fa-circle-info'></i>"
            "Test web search directly. MaxCoder uses this automatically in chat."
            "</div>"
        )
        with gr.Row():
            search_in  = gr.Textbox(
                placeholder="e.g. FastAPI 0.115 release notes",
                label="Query", scale=5)
            search_btn = gr.Button("Search", variant="primary", scale=1)
        search_out = gr.Textbox(
            label="Raw context injected into prompt",
            lines=22, interactive=False)
        search_btn.click(manual_search, [search_in], search_out)
        search_in.submit(manual_search, [search_in], search_out)

    # ══ Runner ════════════════════════════════════════════════════════════════
    with gr.Tab("Runner"):
        gr.HTML(
            "<div class='info-text'>"
            "<i class='fa-solid fa-circle-info'></i>"
            "Paste and run any snippet manually. 20s timeout."
            "</div>"
        )
        with gr.Row():
            run_lang = gr.Dropdown(
                ["python","javascript","bash"],
                value="python", label="Language",
                scale=1, min_width=140)
            run_btn  = gr.Button("Run", variant="primary", scale=1, min_width=90)
        run_code_in  = gr.Code(language="python", label="Code", lines=18)
        run_out_html = gr.HTML()

        def sync_lang(lang):
            return gr.update(language=lang)

        run_lang.change(sync_lang, [run_lang], run_code_in)
        run_btn.click(run_code_manual, [run_code_in, run_lang], run_out_html)

    # ══ Eval ══════════════════════════════════════════════════════════════════
    with gr.Tab("Eval"):
        gr.HTML(
            "<div class='info-text'>"
            "<i class='fa-solid fa-circle-info'></i>"
            "Benchmark quality across correctness, completeness, code quality "
            "and CoT structure. Run before and after fine-tuning to track gains."
            "</div>"
        )
        with gr.Row():
            eval_model    = gr.Dropdown(
                ["maxcoder-fast","maxcoder"],
                value="maxcoder-fast", label="Model", scale=2)
            eval_run_btn  = gr.Button(
                "Run Benchmark", variant="primary",   scale=1)
            eval_load_btn = gr.Button(
                "Load Report",   variant="secondary", scale=1)
        eval_log    = gr.Textbox(label="Progress", lines=10, interactive=False)
        eval_report = gr.Markdown()

        eval_run_btn.click(run_eval,            [eval_model], [eval_log, eval_report])
        eval_load_btn.click(load_latest_report, [eval_model],  eval_report)

    # ══ Status ════════════════════════════════════════════════════════════════
    with gr.Tab("Status"):
        refresh_btn    = gr.Button("Refresh", variant="secondary")
        status_detail  = gr.HTML(check_health())
        refresh_btn.click(check_health, [], status_detail)

if __name__ == "__main__":
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        show_error=True,
    )
