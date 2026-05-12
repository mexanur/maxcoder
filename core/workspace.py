"""
Workspace Manager — each chat/project gets its own isolated folder.

Layout:
  workspace/
  └── <project_id>/
      ├── .maxcoder           ← project metadata (JSON)
      └── <user files...>

All file operations are sandboxed inside workspace/<project_id>/.
"""
from __future__ import annotations

import json, pathlib, datetime, shutil

WORKSPACE_ROOT = pathlib.Path(__file__).parent.parent / "workspace"
WORKSPACE_ROOT.mkdir(exist_ok=True)

META_FILE = ".maxcoder"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _project_dir(project_id: str) -> pathlib.Path:
    p = (WORKSPACE_ROOT / project_id).resolve()
    if not str(p).startswith(str(WORKSPACE_ROOT.resolve())):
        raise PermissionError(f"Invalid project_id: {project_id}")
    return p


def safe_path(project_id: str, rel: str) -> pathlib.Path:
    """Resolve a relative path inside a project dir. Raises on escape attempt."""
    base = _project_dir(project_id)
    p = (base / rel).resolve()
    if not str(p).startswith(str(base.resolve())):
        raise PermissionError(f"Path escapes workspace: {rel}")
    return p


# ── Project lifecycle ─────────────────────────────────────────────────────────

def create_project(project_id: str, name: str = "") -> dict:
    """Create a new project workspace. Returns metadata dict."""
    d = _project_dir(project_id)
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "id":      project_id,
        "name":    name or project_id,
        "created": datetime.datetime.utcnow().isoformat(),
        "updated": datetime.datetime.utcnow().isoformat(),
    }
    (d / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def get_project(project_id: str) -> dict | None:
    """Return project metadata, or None if it doesn't exist."""
    d = _project_dir(project_id)
    meta_path = d / META_FILE
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_or_create_project(project_id: str, name: str = "") -> dict:
    return get_project(project_id) or create_project(project_id, name)


def list_projects() -> list[dict]:
    """Return all projects sorted by updated desc."""
    projects = []
    for meta_path in WORKSPACE_ROOT.glob(f"*/{META_FILE}"):
        try:
            projects.append(json.loads(meta_path.read_text(encoding="utf-8")))
        except Exception:
            pass
    return sorted(projects, key=lambda p: p.get("updated", ""), reverse=True)


def delete_project(project_id: str) -> bool:
    d = _project_dir(project_id)
    if d.exists():
        shutil.rmtree(d)
        return True
    return False


def _touch_project(project_id: str) -> None:
    """Update the project's updated timestamp."""
    d = _project_dir(project_id)
    meta_path = d / META_FILE
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["updated"] = datetime.datetime.utcnow().isoformat()
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        except Exception:
            pass


# ── File operations ───────────────────────────────────────────────────────────

def read_file(project_id: str, rel: str) -> str:
    p = safe_path(project_id, rel)
    if not p.exists():
        return f"ERROR: {rel} does not exist."
    if p.is_dir():
        return f"ERROR: {rel} is a directory."
    return p.read_text(encoding="utf-8", errors="ignore")


def write_file(project_id: str, rel: str, content: str) -> str:
    p = safe_path(project_id, rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _touch_project(project_id)
    return f"OK: wrote {len(content)} chars to {rel}"


def delete_file(project_id: str, rel: str) -> str:
    p = safe_path(project_id, rel)
    if not p.exists():
        return f"ERROR: {rel} does not exist."
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink()
    _touch_project(project_id)
    return f"OK: deleted {rel}"


def list_files(project_id: str) -> list[dict]:
    """
    Return a flat list of all files in the project.
    Each entry: {path, size, is_dir}
    Excludes .maxcoder meta file.
    """
    base = _project_dir(project_id)
    if not base.exists():
        return []
    items = []
    for item in sorted(base.rglob("*")):
        if item.name == META_FILE:
            continue
        rel = str(item.relative_to(base)).replace("\\", "/")
        items.append({
            "path":   rel,
            "size":   item.stat().st_size if item.is_file() else 0,
            "is_dir": item.is_dir(),
        })
    return items


def project_context_snapshot(project_id: str, max_chars_per_file: int = 2000) -> str:
    """
    Build a text snapshot of all project files for injection into the LLM prompt.
    Skips binary files and limits each file to max_chars_per_file chars.
    Total capped at ~12000 chars to stay within 7B context window.
    """
    base = _project_dir(project_id)
    if not base.exists():
        return ""

    BINARY_EXTS = {
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
        ".woff", ".woff2", ".ttf", ".eot",
        ".zip", ".tar", ".gz", ".pdf",
        ".pyc", ".pyd", ".so", ".dll", ".exe",
    }

    sections = []
    total    = 0
    CAP      = 12_000

    for item in sorted(base.rglob("*")):
        if not item.is_file():
            continue
        if item.name == META_FILE:
            continue
        if item.suffix.lower() in BINARY_EXTS:
            continue
        if total >= CAP:
            sections.append("... (more files truncated to fit context)")
            break

        rel     = str(item.relative_to(base)).replace("\\", "/")
        content = item.read_text(encoding="utf-8", errors="ignore")
        if len(content) > max_chars_per_file:
            content = content[:max_chars_per_file] + f"\n... (truncated, {len(content)} chars total)"

        section = f"=== {rel} ===\n{content}"
        sections.append(section)
        total += len(section)

    if not sections:
        return ""

    return "CURRENT PROJECT FILES:\n\n" + "\n\n".join(sections)
