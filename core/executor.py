"""
Code Executor — runs code in a sandbox and feeds errors back to the model
for auto-fixing. Supports Python, JavaScript (Node), Bash.
"""
from __future__ import annotations
import re, subprocess, pathlib, tempfile
from core.generator import generate

SUPPORTED = {
    "python":     ("py",  ["python"]),
    "javascript": ("js",  ["node"]),
    "bash":       ("sh",  ["bash"]),
    "typescript": ("ts",  ["npx", "ts-node"]),
}

FIX_SYSTEM = """You are MaxCoder. The code below produced an error when executed.
Fix the error and output the COMPLETE corrected code only.
No explanations, no markdown prose — just the fixed code block.
"""


def extract_code(text: str, lang: str) -> str | None:
    """Pull the first fenced code block matching lang from LLM output."""
    # Try ```lang ... ``` first
    pattern = rf"```(?:{lang}|{lang.lower()})[^\n]*\n(.*?)```"
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Fallback: any fenced block
    m = re.search(r"```[^\n]*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


def run_snippet(code: str, lang: str, timeout: int = 20) -> dict:
    """Execute a code snippet. Returns {ok, stdout, stderr, code}."""
    spec = SUPPORTED.get(lang.lower())
    if not spec:
        return {"ok": False, "stdout": "", "stderr": f"unsupported lang: {lang}", "code": -1}

    ext, cmd_prefix = spec
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / f"snippet.{ext}"
        p.write_text(code, encoding="utf-8")
        try:
            r = subprocess.run(
                cmd_prefix + [str(p)],
                capture_output=True, text=True, timeout=timeout,
            )
            return {
                "ok": r.returncode == 0,
                "stdout": r.stdout,
                "stderr": r.stderr,
                "code": r.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "stdout": "", "stderr": "timeout (20s)", "code": -1}
        except FileNotFoundError:
            return {"ok": False, "stdout": "",
                    "stderr": f"runtime not installed for {lang}", "code": -1}


async def execute_and_fix(
    llm_response: str,
    lang: str,
    model: str | None = None,
    max_tries: int = 3,
) -> dict:
    """
    Extract code from LLM response, run it, auto-fix on error.

    Returns:
        {ok, code, stdout, stderr, attempts, fixed}
    """
    code = extract_code(llm_response, lang)
    if not code:
        return {"ok": False, "code": None, "stdout": "", "stderr": "no code block found",
                "attempts": 0, "fixed": False}

    fixed = False
    for attempt in range(1, max_tries + 1):
        result = run_snippet(code, lang)
        result["attempts"] = attempt
        result["code_text"] = code
        result["fixed"] = fixed

        if result["ok"]:
            return result

        if attempt == max_tries:
            break

        # Feed the error back to the model
        fix_msgs = [
            {"role": "system", "content": FIX_SYSTEM},
            {"role": "user",
             "content": (
                 f"ERROR:\n{result['stderr']}\n\n"
                 f"CODE:\n```{lang}\n{code}\n```"
             )},
        ]
        fix_response = await generate(fix_msgs, model=model)
        new_code = extract_code(fix_response, lang)
        if new_code and new_code != code:
            code = new_code
            fixed = True

    return result
