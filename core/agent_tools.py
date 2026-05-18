"""
Agent tool registry — the typed surface area an agent loop can call.

Each tool entry has:
  name:        canonical name the model emits
  description: one-line purpose the model sees in the system prompt
  args:        dict of {arg_name: "description"} — also shown to the model
  fn:          async callable that takes **args and returns a string

Design notes:
  • Tools are kept SMALL and FOCUSED. One verb each. The model picks them
    like a human picks library functions.
  • Every fn returns a string — the agent loop treats it as opaque text to
    inject into the next reasoning step. No special "ToolResult" object.
  • All fns wrap exceptions and return "ERROR: ..." strings so the agent
    can SEE the failure and decide how to recover, instead of crashing.
  • The `finish` tool is special: agent loop intercepts it BEFORE calling
    fn, treats its `answer` arg as the final response.
"""
from __future__ import annotations
import asyncio, json
from dataclasses import dataclass
from typing import Awaitable, Callable, Any

from core import tools          as _tools
from core import memory         as _memory
from core import executor       as _exec
from core import rag_retriever  as _rag
from core import web_search     as _web


# ── Tool implementations (all async, all return string) ─────────────────────
async def _t_read_file(rel_path: str) -> str:
    try:
        content = _tools.read_file(rel_path)
        if len(content) > 4000:
            content = content[:4000] + f"\n\n... (truncated, full file is {len(content)} chars)"
        return content
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


async def _t_write_file(rel_path: str, content: str) -> str:
    try:
        return _tools.write_file(rel_path, content)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


async def _t_replace_in_file(rel_path: str, old_string: str, new_string: str,
                              replace_all: bool = False) -> str:
    """Surgical edit: replace `old_string` with `new_string` in an existing file.

    Safer than write_file for targeted changes — the agent doesn't have to
    re-emit the entire file (which 7B models truncate or corrupt). Same
    contract as Anthropic's Edit tool:
      • old_string must appear EXACTLY ONCE in the file (unless replace_all)
      • old_string must be different from new_string
      • file must already exist (use write_file to create)
    """
    # Verify the file exists BEFORE reading — read_file returns an error
    # string (not an exception) on missing files, which would otherwise be
    # treated as the file's content.
    try:
        from core.tools import safe_path as _safe_path
        target_path = _safe_path(rel_path)
        if not target_path.exists():
            return f"ERROR: file not found: {rel_path} — use write_file to create new files"
        existing = target_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

    if not old_string:
        return "ERROR: old_string is empty — refusing to do a no-op replace"
    if old_string == new_string:
        return "ERROR: old_string equals new_string — nothing to change"

    occurrences = existing.count(old_string)
    if occurrences == 0:
        return (f"ERROR: old_string not found in {rel_path}. "
                f"Read the file first to see exact content (whitespace/quotes matter).")
    if occurrences > 1 and not replace_all:
        return (f"ERROR: old_string appears {occurrences} times in {rel_path}. "
                f"Provide more context around it to make it unique, OR set replace_all=true.")

    updated = existing.replace(old_string, new_string)
    try:
        _tools.write_file(rel_path, updated)
    except Exception as e:
        return f"ERROR: write failed: {type(e).__name__}: {e}"

    # Report line numbers of changes for verifiability
    lines = existing.splitlines()
    changed_lines = []
    for i, line in enumerate(lines, 1):
        if old_string.splitlines()[0] in line if old_string else False:
            changed_lines.append(i)

    n = occurrences if replace_all else 1
    suffix = f" (lines around {changed_lines[:5]})" if changed_lines else ""
    return f"Replaced {n} occurrence(s) in {rel_path}{suffix}"


async def _t_list_dir(rel_path: str = ".") -> str:
    try:
        return _tools.list_dir(rel_path)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


async def _t_delete_file(rel_path: str) -> str:
    try:
        return _tools.delete_file(rel_path)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


async def _t_mkdir(rel_path: str) -> str:
    try:
        return _tools.mkdir(rel_path)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


# ── grep — content search across files ──────────────────────────────────────
import re as _re
import fnmatch as _fnmatch
_GREP_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules",
                    ".pytest_cache", ".mypy_cache", "dist", "build", ".idea",
                    ".vscode", "target", ".next", ".cache"}

async def _t_grep(pattern: str, path: str = ".", glob: str = "*",
                   max_results: int = 50, ignore_case: bool = False) -> str:
    """Search for `pattern` (Python regex) across files under `path`.

    Returns matches in `filename:line_number: matched line` format. Caps at
    `max_results` so the agent doesn't drown in output. Skips well-known
    junk directories (.git, .venv, node_modules, build artifacts).
    """
    try:
        base = _tools.safe_path(path)
        if not base.exists():
            return f"ERROR: path not found: {path}"
        try:
            regex = _re.compile(pattern, _re.IGNORECASE if ignore_case else 0)
        except _re.error as e:
            return f"ERROR: invalid regex {pattern!r}: {e}"

        targets = []
        if base.is_file():
            targets = [base]
        else:
            for p in base.rglob("*"):
                # Skip dirs in the junk-list (check any ancestor)
                if any(part in _GREP_SKIP_DIRS for part in p.parts):
                    continue
                if not p.is_file():
                    continue
                if glob and not _fnmatch.fnmatch(p.name, glob):
                    continue
                targets.append(p)

        results = []
        for fp in targets:
            try:
                # Skip binary-looking files (cheap heuristic)
                head = fp.read_bytes()[:512]
                if b"\x00" in head:
                    continue
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            rel = fp.relative_to(_tools.WORKSPACE)
            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    results.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(results) >= max_results:
                        break
            if len(results) >= max_results:
                results.append(f"... (truncated at {max_results} matches)")
                break
        return "\n".join(results) if results else f"(no matches for {pattern!r})"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


# ── run_shell — allowlisted shell command execution ─────────────────────────
import shlex as _shlex
import subprocess as _subprocess

# First-word allowlist. ONLY commands starting with one of these tokens are
# permitted. This is intentionally conservative — start narrow, widen as needed.
_SHELL_ALLOWLIST = {
    # Read-only inspection
    "ls", "pwd", "echo", "cat", "head", "tail", "wc", "find", "which", "file",
    # Version control (read + safe write)
    "git",
    # Python ecosystem
    "python", "python3", "pip", "pip3", "pytest", "black", "ruff", "mypy",
    # Node ecosystem
    "node", "npm", "pnpm", "yarn", "tsc", "prettier", "eslint",
    # Rust
    "cargo", "rustc", "rustfmt",
    # Go
    "go", "gofmt",
    # Build / dev
    "make", "cmake",
    # Misc
    "date", "uname", "env",
}

# Characters that allow command chaining or escaping the sandbox cwd. Reject
# any command containing these — they let the model bypass the allowlist.
_SHELL_FORBIDDEN_CHARS = set("|&;`$><\n")


async def _t_run_shell(command: str, timeout: int = 60) -> str:
    """Run an allowlisted shell command inside the workspace directory.

    Safety:
      • First word must be in _SHELL_ALLOWLIST (no `rm`, no `curl`, etc.)
      • Forbidden chars (| & ; ` $ > < newline) block command chaining
      • Working directory is the sandboxed workspace
      • Hard timeout (default 60s)
      • shell=False — no shell interpolation; uses shlex.split
    """
    try:
        cmd = (command or "").strip()
        if not cmd:
            return "ERROR: empty command"
        if any(ch in cmd for ch in _SHELL_FORBIDDEN_CHARS):
            return ("ERROR: command contains forbidden character(s) "
                    "(|, &, ;, `, $, >, <, newline). Command chaining is not "
                    "allowed — call run_shell once per command.")
        try:
            argv = _shlex.split(cmd, posix=True)
        except ValueError as e:
            return f"ERROR: cannot parse command: {e}"
        if not argv:
            return "ERROR: empty command after parsing"
        verb = argv[0].split("/")[-1]  # strip any path prefix
        if verb not in _SHELL_ALLOWLIST:
            return (f"ERROR: '{verb}' is not in the shell allowlist. "
                    f"Allowed verbs: {sorted(_SHELL_ALLOWLIST)}")

        # Run in workspace with hard timeout
        try:
            result = await asyncio.to_thread(
                _subprocess.run,
                argv,
                cwd=str(_tools.WORKSPACE),
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
        except _subprocess.TimeoutExpired:
            return f"ERROR: command exceeded {timeout}s timeout"
        except FileNotFoundError:
            return f"ERROR: '{verb}' executable not found on PATH"

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        # Truncate verbose output so we don't blow up the agent context
        if len(stdout) > 3500:
            stdout = stdout[:3500] + f"\n... (stdout truncated, {len(result.stdout)} chars total)"
        if len(stderr) > 1500:
            stderr = stderr[:1500] + f"\n... (stderr truncated)"

        parts = [f"[exit {result.returncode}]"]
        if stdout: parts.append(f"STDOUT:\n{stdout}")
        if stderr: parts.append(f"STDERR:\n{stderr}")
        if not stdout and not stderr:
            parts.append("(no output)")
        return "\n".join(parts)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


async def _t_fetch_url(url: str) -> str:
    try:
        out = await _tools.fetch_url(url)
        if len(out) > 4000:
            out = out[:4000] + f"\n\n... (truncated, full page is {len(out)} chars)"
        return out
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


async def _t_search_web(query: str) -> str:
    try:
        ctx = await _web.web_context(query)
        if not ctx or not ctx.strip():
            return "(no relevant web results)"
        if len(ctx) > 4000:
            ctx = ctx[:4000] + "\n\n... (truncated)"
        return ctx
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


async def _t_search_memory(query: str) -> str:
    try:
        ctx = _memory.retrieve(query, k=5)
        return ctx or "(no relevant memories)"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


async def _t_save_memory(text: str, category: str = "general") -> str:
    try:
        _memory.save(text, category=category)
        return "Saved to memory."
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


async def _t_search_docs(query: str) -> str:
    try:
        ctx = _rag.retrieve(query, k_per_index=3)
        return ctx or "(no relevant docs)"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


async def _t_run_python(code: str) -> str:
    try:
        # Run on a background thread so the agent loop stays responsive.
        result = await asyncio.to_thread(
            _exec.run_snippet, code, "python", True,
        )
        ok = result.get("ok", False)
        out = result.get("stdout", "") or ""
        err = result.get("stderr", "") or ""
        parts = []
        if out: parts.append(f"STDOUT:\n{out.strip()}")
        if err: parts.append(f"STDERR:\n{err.strip()}")
        if not parts:
            parts.append("(no output)")
        prefix = "OK" if ok else "FAILED"
        return f"[{prefix}]\n" + "\n".join(parts)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


# ── Tool registry ───────────────────────────────────────────────────────────
@dataclass
class ToolSpec:
    name:        str
    description: str
    args:        dict     # {arg_name: "description"}
    fn:          Callable[..., Awaitable[str]]

    def schema_line(self) -> str:
        """One-line schema for the system prompt."""
        if not self.args:
            return f'  • {self.name}() — {self.description}'
        args_str = ", ".join(f'{k}: "{v}"' for k, v in self.args.items())
        return f'  • {self.name}({args_str}) — {self.description}'


TOOLS: dict[str, ToolSpec] = {
    "read_file": ToolSpec(
        name="read_file",
        description="Read a text file from the workspace. Returns its content (truncated to 4000 chars).",
        args={"rel_path": "path relative to the workspace, e.g. 'src/main.py'"},
        fn=_t_read_file,
    ),
    "write_file": ToolSpec(
        name="write_file",
        description="Write/overwrite a text file in the workspace with the FULL new content. Use this to create new files or completely replace existing ones.",
        args={"rel_path": "path", "content": "full file content as a string"},
        fn=_t_write_file,
    ),
    "replace_in_file": ToolSpec(
        name="replace_in_file",
        description="Surgical edit: replace an exact substring with new text in an existing file. Safer than write_file for targeted changes (no risk of truncating the rest of the file). old_string must match exactly and be unique unless replace_all=true.",
        args={
            "rel_path":    "path to the file (must already exist)",
            "old_string":  "exact substring to find — include enough surrounding context to be unique",
            "new_string":  "replacement text",
            "replace_all": "set true to replace ALL occurrences instead of failing on multiple matches",
        },
        fn=_t_replace_in_file,
    ),
    "list_dir": ToolSpec(
        name="list_dir",
        description="List files and folders at a workspace path.",
        args={"rel_path": "directory to list, default '.'"},
        fn=_t_list_dir,
    ),
    "delete_file": ToolSpec(
        name="delete_file",
        description="Delete a file inside the workspace.",
        args={"rel_path": "path to the file to delete"},
        fn=_t_delete_file,
    ),
    "mkdir": ToolSpec(
        name="mkdir",
        description="Create a directory (and any missing parent directories) inside the workspace.",
        args={"rel_path": "directory path to create"},
        fn=_t_mkdir,
    ),
    "grep": ToolSpec(
        name="grep",
        description="Search for a regex pattern across files under a workspace path. Returns 'filename:line_number: line' for each match (capped at max_results). Skips .git, .venv, node_modules and other junk dirs.",
        args={
            "pattern":      "regex pattern to find",
            "path":         "directory or file to search, default '.'",
            "glob":         "filename glob filter (e.g. '*.py'), default '*'",
            "max_results":  "cap on number of matches returned, default 50",
            "ignore_case":  "set true for case-insensitive search",
        },
        fn=_t_grep,
    ),
    "run_shell": ToolSpec(
        name="run_shell",
        description=(
            "Run an allowlisted shell command inside the workspace. Use for git "
            "(status/diff/log/branch), package managers (pip/npm/cargo/go), test "
            "runners (pytest), formatters (black/prettier), and basic inspection "
            "(ls/cat/find). Returns exit code + stdout + stderr. "
            "NOT allowed: rm, curl, sudo, shell redirection (|, &, ;, >, <), or "
            "any command that chains other commands. Run one command at a time."
        ),
        args={
            "command": "the full command, e.g. 'git status' or 'pytest tests/'",
            "timeout": "hard timeout in seconds, default 60",
        },
        fn=_t_run_shell,
    ),
    "fetch_url": ToolSpec(
        name="fetch_url",
        description="Fetch and return the text content of a specific URL.",
        args={"url": "full URL starting with http:// or https://"},
        fn=_t_fetch_url,
    ),
    "search_web": ToolSpec(
        name="search_web",
        description="Search the web (DuckDuckGo) and return concatenated snippets from the top pages.",
        args={"query": "search query in natural language"},
        fn=_t_search_web,
    ),
    "search_memory": ToolSpec(
        name="search_memory",
        description="Recall facts from long-term memory (user preferences, prior decisions, project facts).",
        args={"query": "what you're looking for, in natural language"},
        fn=_t_search_memory,
    ),
    "save_memory": ToolSpec(
        name="save_memory",
        description="Save a fact to long-term memory for future sessions. Use sparingly — only for stable, useful facts.",
        args={"text": "the fact to remember", "category": "tag like 'preference' or 'project_fact'"},
        fn=_t_save_memory,
    ),
    "search_docs": ToolSpec(
        name="search_docs",
        description="Search local indexed documentation (language docs, codebase, error solutions, snippets).",
        args={"query": "what to search for"},
        fn=_t_search_docs,
    ),
    "run_python": ToolSpec(
        name="run_python",
        description="Execute a Python snippet in a sandbox and return stdout/stderr. Use for math, calculations, data manipulation, verification.",
        args={"code": "the Python code to run"},
        fn=_t_run_python,
    ),
    # `finish` is special — agent loop intercepts before fn is called
    "finish": ToolSpec(
        name="finish",
        description="Return the final answer to the user. Call this when you have everything you need.",
        args={"answer": "the complete final answer in plain text"},
        fn=None,  # type: ignore
    ),
}


def tools_for_prompt() -> str:
    """Render the tool registry as a block the LLM can read."""
    return "\n".join(spec.schema_line() for spec in TOOLS.values())


async def dispatch(name: str, args: dict) -> str:
    """Look up and invoke a tool. Returns a string result (errors are
    serialized as 'ERROR: ...' rather than raising)."""
    spec = TOOLS.get(name)
    if spec is None:
        return f"ERROR: unknown tool {name!r}. Available: {list(TOOLS.keys())}"
    if spec.fn is None:
        return f"ERROR: {name} is a control-flow tool — do not dispatch directly"
    # Filter args to the tool's declared kwargs
    valid_args = {k: v for k, v in (args or {}).items() if k in spec.args}
    try:
        return await spec.fn(**valid_args)
    except TypeError as e:
        return f"ERROR: bad args for {name}: {e}. Expected: {list(spec.args.keys())}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"
