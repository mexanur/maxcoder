"""
Agent Parser — extracts structured file operation commands from LLM output.

The LLM is instructed to output commands in this format:

  @@CREATE path/to/file.ext
  ```lang
  <full file content>
  ```

  @@EDIT path/to/file.ext
  ```lang
  <full updated file content>
  ```

  @@DELETE path/to/file.ext

  @@RUN lang
  ```lang
  <code to execute>
  ```

Using @@CREATE and @@EDIT with full file content (not diffs) is intentional:
diffs are unreliable on 3B-7B models. Full-file replace is simpler and safer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class FileOp:
    op:      str          # "create" | "edit" | "delete" | "run"
    path:    str          # relative file path (empty for "run")
    lang:    str = ""     # detected language
    content: str = ""     # file content or code to run


def parse_agent_response(text: str) -> tuple[list[FileOp], str]:
    """
    Parse agent response and extract all FileOps.

    Returns:
        ops      — list of FileOp
        clean    — the response text with @@-blocks removed (chat portion only)
    """
    ops: list[FileOp] = []

    # ── @@CREATE / @@EDIT  ────────────────────────────────────────────────────
    for m in re.finditer(
        r"@@(CREATE|EDIT)[ \t]+([^\n]+)\n```(\w*)[ \t]*\n([\s\S]*?)```",
        text, re.IGNORECASE
    ):
        op_type = m.group(1).lower()
        path    = m.group(2).strip()
        lang    = m.group(3).strip().lower() or _lang_from_path(path)
        content = m.group(4)
        # Normalise: strip one leading newline if present
        if content.startswith("\n"):
            content = content[1:]
        ops.append(FileOp(op=op_type, path=path, lang=lang, content=content))

    # ── @@DELETE  ─────────────────────────────────────────────────────────────
    for m in re.finditer(r"@@DELETE[ \t]+([^\n]+)", text, re.IGNORECASE):
        ops.append(FileOp(op="delete", path=m.group(1).strip()))

    # ── @@RUN  ────────────────────────────────────────────────────────────────
    for m in re.finditer(
        r"@@RUN[ \t]+(\w+)\n```(?:\w*)[ \t]*\n([\s\S]*?)```",
        text, re.IGNORECASE
    ):
        lang    = m.group(1).strip().lower()
        content = m.group(2)
        if content.startswith("\n"):
            content = content[1:]
        ops.append(FileOp(op="run", path="", lang=lang, content=content))

    # ── Clean text — remove all @@-blocks so chat prose remains ──────────────
    clean = re.sub(
        r"@@(?:CREATE|EDIT|DELETE|RUN)[^\n]*\n(?:```[\s\S]*?```)?",
        "", text, flags=re.IGNORECASE
    ).strip()

    return ops, clean


def _lang_from_path(path: str) -> str:
    """Guess language from file extension."""
    ext_map = {
        ".py":    "python",
        ".js":    "javascript",
        ".jsx":   "jsx",
        ".ts":    "typescript",
        ".tsx":   "tsx",
        ".html":  "html",
        ".css":   "css",
        ".json":  "json",
        ".md":    "markdown",
        ".sh":    "bash",
        ".rs":    "rust",
        ".go":    "go",
        ".java":  "java",
        ".sql":   "sql",
        ".yaml":  "yaml",
        ".yml":   "yaml",
        ".toml":  "toml",
        ".env":   "bash",
        ".txt":   "text",
    }
    suffix = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return ext_map.get(suffix, "text")
