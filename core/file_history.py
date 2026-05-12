"""
File History — lightweight per-project undo stack.

Stores snapshots in workspace/<project_id>/.history/<file_path>/<timestamp>.snap
No git dependency. Keeps last MAX_SNAPS versions per file.
"""
from __future__ import annotations

import datetime, pathlib, shutil
from core.workspace import WORKSPACE_ROOT, safe_path

MAX_SNAPS = 20  # keep last 20 versions per file


def _history_dir(project_id: str, rel: str) -> pathlib.Path:
    base = WORKSPACE_ROOT / project_id / ".history" / rel
    base.mkdir(parents=True, exist_ok=True)
    return base


def snapshot(project_id: str, rel: str) -> str | None:
    """
    Save a snapshot of rel BEFORE it is overwritten.
    Call this just before write_file(). Returns snapshot path or None.
    """
    src = safe_path(project_id, rel)
    if not src.exists() or src.is_dir():
        return None

    hdir  = _history_dir(project_id, rel)
    stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S%f")
    dest  = hdir / f"{stamp}.snap"
    shutil.copy2(src, dest)

    # Prune oldest snaps
    snaps = sorted(hdir.glob("*.snap"))
    for old in snaps[:-MAX_SNAPS]:
        old.unlink(missing_ok=True)

    return str(dest)


def list_snapshots(project_id: str, rel: str) -> list[dict]:
    """Return list of snapshots newest-first: [{stamp, path}]"""
    hdir = WORKSPACE_ROOT / project_id / ".history" / rel
    if not hdir.exists():
        return []
    snaps = sorted(hdir.glob("*.snap"), reverse=True)
    return [
        {"stamp": s.stem, "path": str(s.relative_to(WORKSPACE_ROOT / project_id))}
        for s in snaps
    ]


def restore_snapshot(project_id: str, rel: str, stamp: str) -> str:
    """Restore file to a previous snapshot. Returns status message."""
    hdir = WORKSPACE_ROOT / project_id / ".history" / rel
    snap = hdir / f"{stamp}.snap"
    if not snap.exists():
        return f"ERROR: snapshot {stamp} not found for {rel}"

    # Save current as snapshot before restoring
    snapshot(project_id, rel)

    dest = safe_path(project_id, rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(snap, dest)
    return f"OK: {rel} restored to {stamp}"


def get_snapshot_content(project_id: str, rel: str, stamp: str) -> str:
    """Read a snapshot's content without restoring it."""
    hdir = WORKSPACE_ROOT / project_id / ".history" / rel
    snap = hdir / f"{stamp}.snap"
    if not snap.exists():
        return f"ERROR: snapshot {stamp} not found"
    return snap.read_text(encoding="utf-8", errors="ignore")
