"""
MaxCoder v2 Gradio UI.
"""
import os, httpx, gradio as gr

BACKEND = os.getenv("MAXCODER_BACKEND", "http://127.0.0.1:8000")

# ── Chat fn (streaming) ───────────────────────────────────────────────────────
def chat_fn(message, history, model, use_rag, use_memory, use_rewriter, use_critic):
    msgs = []
    for u, a in history:
        msgs.append({"role": "user",    "content": u})
        if a: msgs.append({"role": "assistant", "content": a})
    msgs.append({"role": "user", "content": message})

    payload = {
        "messages":     msgs,
        "model":        model,
        "use_rag":      use_rag,
        "use_memory":   use_memory,
        "use_rewriter": use_rewriter,
        "use_critic":   use_critic,
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
        yield f"⚠️ Backend error: {e}\nMake sure `uvicorn server.app:app` is running."


# ── Memory helpers ────────────────────────────────────────────────────────────
def add_memory(text, category):
    if not text.strip():
        return "⚠️ Empty memory text."
    try:
        r = httpx.post(f"{BACKEND}/memory/add",
                       json={"text": text, "category": category}, timeout=10)
        return "✅ Memory saved." if r.status_code == 200 else f"Error: {r.text}"
    except Exception as e:
        return f"⚠️ {e}"

def list_memories():
    try:
        r = httpx.get(f"{BACKEND}/memory/list", timeout=10)
        mems = r.json().get("memories", [])
        if not mems: return "No memories stored yet."
        return "\n".join(f"{i+1}. {m}" for i, m in enumerate(mems))
    except Exception as e:
        return f"⚠️ {e}"

def clear_memories():
    try:
        httpx.delete(f"{BACKEND}/memory/clear", timeout=10)
        return "🗑️ All memories cleared."
    except Exception as e:
        return f"⚠️ {e}"


# ── Code runner ───────────────────────────────────────────────────────────────
def run_code(code, lang):
    if not code.strip():
        return "⚠️ No code to run."
    try:
        r = httpx.post(f"{BACKEND}/run",
                       json={"code": code, "lang": lang}, timeout=30)
        d = r.json()
        out = []
        if d.get("stdout"): out.append(f"**stdout:**\n```\n{d['stdout']}\n```")
        if d.get("stderr"): out.append(f"**stderr:**\n```\n{d['stderr']}\n```")
        status = "✅ exit 0" if d.get("ok") else f"❌ exit {d.get('code','?')}"
        return status + "\n\n" + "\n".join(out)
    except Exception as e:
        return f"⚠️ {e}"


# ── Health check ──────────────────────────────────────────────────────────────
def check_health():
    try:
        r = httpx.get(f"{BACKEND}/health", timeout=5)
        d = r.json()
        if d.get("ok"):
            models = ", ".join(d.get("models", []))
            return f"🟢 Backend up  |  Models: {models}"
        return f"🔴 {d.get('error')}"
    except Exception as e:
        return f"🔴 Backend unreachable: {e}"


# ── Build UI ──────────────────────────────────────────────────────────────────
with gr.Blocks(title="MaxCoder v2", theme=gr.themes.Soft()) as demo:

    gr.Markdown("# 🛠️ MaxCoder v2 — Local Coding LLM")
    gr.Markdown(check_health())

    with gr.Tab("💬 Chat"):
        model_dd = gr.Dropdown(
            ["maxcoder-fast", "maxcoder"],
            value="maxcoder-fast",
            label="Model (fast=3B full-GPU | quality=7B partial-GPU)")
        with gr.Row():
            use_rag      = gr.Checkbox(value=True,  label="🔍 RAG")
            use_memory   = gr.Checkbox(value=True,  label="🧠 Memory")
            use_rewriter = gr.Checkbox(value=True,  label="✏️ Rewriter")
            use_critic   = gr.Checkbox(value=False, label="🔄 Critic (slower)")

        gr.ChatInterface(
            fn=chat_fn,
            additional_inputs=[model_dd, use_rag, use_memory, use_rewriter, use_critic],
        )

    with gr.Tab("🧠 Memory"):
        gr.Markdown("### Teach MaxCoder about your preferences")
        with gr.Row():
            mem_text = gr.Textbox(
                label="Memory fact",
                placeholder='e.g. "I always use PostgreSQL"',
                lines=2)
            mem_cat = gr.Dropdown(
                ["general", "tech_stack", "style", "project", "constraint"],
                value="general", label="Category")
        mem_add_btn  = gr.Button("💾 Save memory", variant="primary")
        mem_status   = gr.Markdown()
        mem_list_btn = gr.Button("📋 List all memories")
        mem_list_out = gr.Textbox(label="Stored memories", lines=10, interactive=False)
        mem_clear_btn = gr.Button("🗑️ Clear all memories", variant="stop")
        mem_clear_out = gr.Markdown()

        mem_add_btn.click(add_memory,     [mem_text, mem_cat], mem_status)
        mem_list_btn.click(list_memories, [],                  mem_list_out)
        mem_clear_btn.click(clear_memories, [],                mem_clear_out)

    with gr.Tab("⚡ Code Runner"):
        gr.Markdown("### Run a snippet directly (20s timeout)")
        run_lang    = gr.Dropdown(["python","javascript","bash"], value="python", label="Language")
        run_code_in = gr.Code(language="python", label="Code", lines=15)
        run_btn     = gr.Button("▶ Run", variant="primary")
        run_out     = gr.Markdown(label="Output")
        run_btn.click(run_code, [run_code_in, run_lang], run_out)

    with gr.Tab("ℹ️ Status"):
        refresh_btn = gr.Button("🔄 Refresh")
        status_out  = gr.Markdown(check_health())
        refresh_btn.click(check_health, [], status_out)

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, show_error=True)
