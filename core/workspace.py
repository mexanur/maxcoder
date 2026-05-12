"""
Workspace Manager — each chat/project gets its own isolated folder.

Layout:
  workspace/
  └── <project_id>/
      ├── .maxcoder           ← project metadata (JSON)
      ├── .history/           ← auto-snapshots (undo support)
      ├── .db/                ← per-project SQLite DB
      └── <user files...>
"""
from __future__ import annotations

import json, pathlib, datetime, shutil

WORKSPACE_ROOT = pathlib.Path(__file__).parent.parent / "workspace"
WORKSPACE_ROOT.mkdir(exist_ok=True)

META_FILE = ".maxcoder"
SKIP_DIRS = {".history", ".db"}


def _project_dir(project_id: str) -> pathlib.Path:
    p = (WORKSPACE_ROOT / project_id).resolve()
    if not str(p).startswith(str(WORKSPACE_ROOT.resolve())):
        raise PermissionError(f"Invalid project_id: {project_id}")
    return p


def safe_path(project_id: str, rel: str) -> pathlib.Path:
    base = _project_dir(project_id)
    p = (base / rel).resolve()
    if not str(p).startswith(str(base.resolve())):
        raise PermissionError(f"Path escapes workspace: {rel}")
    return p


def create_project(project_id: str, name: str = "") -> dict:
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
    d = _project_dir(project_id)
    meta_path = d / META_FILE
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["updated"] = datetime.datetime.utcnow().isoformat()
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        except Exception:
            pass


def read_file(project_id: str, rel: str) -> str:
    p = safe_path(project_id, rel)
    if not p.exists():
        return f"ERROR: {rel} does not exist."
    if p.is_dir():
        return f"ERROR: {rel} is a directory."
    return p.read_text(encoding="utf-8", errors="ignore")


def write_file(project_id: str, rel: str, content: str) -> str:
    """Write file, auto-snapshotting the previous version for undo support."""
    p = safe_path(project_id, rel)

    # Auto-snapshot before overwrite
    if p.exists() and p.is_file():
        try:
            from core.file_history import snapshot
            snapshot(project_id, rel)
        except Exception:
            pass  # never block a write due to history failure

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _touch_project(project_id)
    return f"OK: wrote {len(content)} chars to {rel}"


def delete_file(project_id: str, rel: str) -> str:
    p = safe_path(project_id, rel)
    if not p.exists():
        return f"ERROR: {rel} does not exist."

    # Snapshot before delete
    if p.is_file():
        try:
            from core.file_history import snapshot
            snapshot(project_id, rel)
        except Exception:
            pass

    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink()
    _touch_project(project_id)
    return f"OK: deleted {rel}"


def list_files(project_id: str) -> list[dict]:
    base = _project_dir(project_id)
    if not base.exists():
        return []
    items = []
    for item in sorted(base.rglob("*")):
        # Skip internal dirs
        parts = item.relative_to(base).parts
        if any(p in SKIP_DIRS for p in parts):
            continue
        if item.name == META_FILE:
            continue
        rel = str(item.relative_to(base)).replace("\\", "/")
        items.append({
            "path":   rel,
            "size":   item.stat().st_size if item.is_file() else 0,
            "is_dir": item.is_dir(),
        })
    return items


BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".pdf",
    ".pyc", ".pyd", ".so", ".dll", ".exe",
}


def project_context_snapshot(project_id: str, max_chars_per_file: int = 2000) -> str:
    """
    Full snapshot of all project files (used as fallback when context_selector
    is not available). Capped at 12,000 chars total.
    """
    base = _project_dir(project_id)
    if not base.exists():
        return ""

    sections = []
    total    = 0
    CAP      = 12_000

    for item in sorted(base.rglob("*")):
        parts = item.relative_to(base).parts
        if any(p in SKIP_DIRS for p in parts):
            continue
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
