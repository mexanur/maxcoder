"""
Tool definitions — file I/O, directory listing, URL fetch.
These are injected as context when the model requests them via
special markers in its output.
"""
from __future__ import annotations
import pathlib, re

# Root allowed for file operations (security: stay inside project)
WORKSPACE = pathlib.Path.cwd() / "workspace"
WORKSPACE.mkdir(exist_ok=True)


def safe_path(rel: str) -> pathlib.Path:
    p = (WORKSPACE / rel).resolve()
    if not str(p).startswith(str(WORKSPACE.resolve())):
        raise PermissionError(f"Path escapes workspace: {rel}")
    return p


def read_file(rel_path: str) -> str:
    p = safe_path(rel_path)
    if not p.exists():
        return f"ERROR: {rel_path} does not exist."
    return p.read_text(encoding="utf-8", errors="ignore")


def write_file(rel_path: str, content: str) -> str:
    p = safe_path(rel_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"OK: wrote {len(content)} chars to {rel_path}"


def list_dir(rel_path: str = ".") -> str:
    p = safe_path(rel_path)
    if not p.exists():
        return f"ERROR: {rel_path} does not exist."
    lines = []
    for item in sorted(p.rglob("*")):
        rel = item.relative_to(WORKSPACE)
        prefix = "📁" if item.is_dir() else "📄"
        lines.append(f"{prefix} {rel}")
    return "\n".join(lines) if lines else "(empty)"


def delete_file(rel_path: str) -> str:
    p = safe_path(rel_path)
    if not p.exists():
        return f"ERROR: {rel_path} does not exist."
    p.unlink()
    return f"OK: deleted {rel_path}"


async def fetch_url(url: str) -> str:
    """Fetch a URL and return its text content (first 4000 chars)."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "MaxCoder/2.0"})
            return r.text[:4000]
    except Exception as e:
        return f"ERROR fetching {url}: {e}"


def parse_tool_calls(text: str) -> list[dict]:
    """
    Detect tool call markers in model output.
    Format the model is instructed to use:
      <tool:read_file path="src/main.py"/>
      <tool:write_file path="src/main.py">...content...</tool:write_file>
      <tool:list_dir path="."/>
      <tool:fetch_url url="https://..."/>
    """
    calls = []

    # Self-closing: read_file, list_dir, fetch_url
    for m in re.finditer(
        r'<tool:(read_file|list_dir|fetch_url)\s+(\w+)="([^"]+)"\s*/>', text
    ):
        calls.append({"tool": m.group(1), "arg_name": m.group(2), "arg": m.group(3)})

    # Block: write_file
    for m in re.finditer(
        r'<tool:write_file\s+path="([^"]+)">(.*?)</tool:write_file>', text, re.DOTALL
    ):
        calls.append({"tool": "write_file", "path": m.group(1), "content": m.group(2)})

    return calls


async def dispatch(call: dict) -> str:
    """Execute a parsed tool call and return its result."""
    t = call["tool"]
    if t == "read_file":
        return read_file(call["arg"])
    if t == "list_dir":
        return list_dir(call["arg"])
    if t == "fetch_url":
        return await fetch_url(call["arg"])
    if t == "write_file":
        return write_file(call["path"], call["content"])
    return f"Unknown tool: {t}"
