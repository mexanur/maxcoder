"""
MaxCoder Executor.
- Uses .venv Python so all installed packages are available
- Auto-installs missing pip packages on ModuleNotFoundError
- HTML/CSS/JS returned as-is for browser preview
- Proper language detection
"""
from __future__ import annotations

import re, subprocess, pathlib, tempfile, sys, os

# ── Find the .venv Python ─────────────────────────────────────────────────────
def _find_python() -> str:
    """Return path to .venv Python, fallback to sys.executable."""
    base = pathlib.Path(__file__).parent.parent
    candidates = [
        base / ".venv" / "Scripts" / "python.exe",  # Windows
        base / ".venv" / "bin" / "python",           # Linux/macOS
        base / ".venv" / "Scripts" / "python",       # Windows alt
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return sys.executable  # fallback

VENV_PYTHON = _find_python()

SUPPORTED = {
    "python":     ("py",  [VENV_PYTHON]),
    "javascript": ("js",  ["node"]),
    "bash":       ("sh",  ["bash"]),
    "shell":      ("sh",  ["bash"]),
    "typescript": ("ts",  ["npx", "--yes", "ts-node"]),
}

# Languages that should NOT be executed (returned for preview)
PREVIEW_LANGS = {"html", "svg", "xml", "markdown", "md", ""}

# ── Auto-install helper ───────────────────────────────────────────────────────
def _extract_missing_module(stderr: str) -> str | None:
    m = re.search(r"No module named '([^']+)'", stderr)
    return m.group(1).split(".")[0] if m else None

def _try_install(module: str) -> tuple[bool, str]:
    """Try pip install <module>. Returns (success, output)."""
    try:
        r = subprocess.run(
            [VENV_PYTHON, "-m", "pip", "install", module, "-q"],
            capture_output=True, text=True, timeout=60
        )
        return r.returncode == 0, r.stdout + r.stderr
    except Exception as e:
        return False, str(e)

# ── Main runner ───────────────────────────────────────────────────────────────
def run_snippet(
    code: str,
    lang: str,
    timeout: int = 20,
    auto_install: bool = True,
) -> dict:
    """
    Execute a code snippet.
    Returns {ok, stdout, stderr, code, lang, preview_html}
    """
    lang = (lang or "").lower().strip()

    # HTML → return as-is for browser preview
    if lang in PREVIEW_LANGS or lang == "html":
        return {
            "ok": True, "stdout": "", "stderr": "",
            "code": 0, "lang": lang,
            "preview_html": code,
        }

    # CSS → wrap in a styled preview page (FIXED: was truncated/broken)
    if lang == "css":
        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{code}
</style>
</head>
<body>
  <div class="preview-root">
    <p>CSS Preview — elements styled by your code:</p>
    <h1>Heading 1</h1>
    <h2>Heading 2</h2>
    <p>Paragraph text. <a href="#">A link</a>. <strong>Bold</strong>. <em>Italic</em>.</p>
    <button>Button</button>
    <input type="text" placeholder="Input field" />
    <ul><li>List item one</li><li>List item two</li></ul>
  </div>
</body>
</html>"""
        return {
            "ok": True, "stdout": "", "stderr": "",
            "code": 0, "lang": lang, "preview_html": html,
        }

    spec = SUPPORTED.get(lang)
    if not spec:
        return {
            "ok": False, "stdout": "", "lang": lang,
            "stderr": (
                f"Language '{lang}' cannot be executed directly.\n"
                f"Supported: {', '.join(SUPPORTED.keys())}"
            ),
            "code": -1, "preview_html": None,
        }

    ext, cmd = spec

    def _run(c: str) -> dict:
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / f"snippet.{ext}"
            p.write_text(c, encoding="utf-8")
            try:
                r = subprocess.run(
                    cmd + [str(p)],
                    capture_output=True, text=True, timeout=timeout,
                    env={**os.environ, "PYTHONPATH": ""},
                )
                return {
                    "ok": r.returncode == 0,
                    "stdout": r.stdout,
                    "stderr": r.stderr,
                    "code": r.returncode,
                    "lang": lang,
                    "preview_html": None,
                }
            except subprocess.TimeoutExpired:
                return {
                    "ok": False, "stdout": "", "lang": lang,
                    "stderr": f"Timeout ({timeout}s) — code ran too long.",
                    "code": -1, "preview_html": None,
                }
            except FileNotFoundError:
                return {
                    "ok": False, "stdout": "", "lang": lang,
                    "stderr": f"Runtime not found for '{lang}'. Is it installed?",
                    "code": -1, "preview_html": None,
                }

    result = _run(code)

    # Auto-install missing package and retry once
    if (
        not result["ok"]
        and auto_install
        and lang == "python"
        and "ModuleNotFoundError" in result.get("stderr", "")
    ):
        missing = _extract_missing_module(result["stderr"])
        if missing:
            ok, pip_out = _try_install(missing)
            if ok:
                result = _run(code)
                result["stderr"] = (
                    f"[auto-installed '{missing}']\n" + result.get("stderr", "")
                )
            else:
                result["stderr"] += f"\n[pip install {missing} failed]\n{pip_out}"

    return result


async def execute_and_fix(
    llm_response: str,
    lang: str,
    model: str | None = None,
    max_tries: int = 3,
) -> dict:
    """Extract code from LLM response, run, auto-fix on errors."""
    from core.generator import generate

    pattern = rf"```(?:{lang}|{lang.lower()}|python)[^\n]*\n([\s\S]*?)```"
    m = re.search(pattern, llm_response, re.IGNORECASE)
    if not m:
        m = re.search(r"```[^\n]*\n([\s\S]*?)```", llm_response)
    code = m.group(1).strip() if m else None

    if not code:
        return {
            "ok": False, "code": None,
            "stdout": "", "stderr": "no code block found", "attempts": 0,
        }

    FIX_SYSTEM = "Fix the error in the code below. Output ONLY the corrected code block."

    for attempt in range(1, max_tries + 1):
        result = run_snippet(code, lang)
        result["attempts"] = attempt
        if result["ok"]:
            return result
        if attempt == max_tries:
            break
        fix_msgs = [
            {"role": "system",  "content": FIX_SYSTEM},
            {"role": "user",    "content": f"ERROR:\n{result['stderr']}\n\nCODE:\n```{lang}\n{code}\n```"},
        ]
        fix   = await generate(fix_msgs, model=model)
        new_m = re.search(r"```[^\n]*\n([\s\S]*?)```", fix)
        if new_m:
            code = new_m.group(1).strip()

    return result
