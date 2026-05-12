"""
SQL Runner — executes SQL against a per-project SQLite database.

Each project gets its own DB at workspace/<project_id>/.db/project.sqlite
Supports SELECT (returns rows as list[dict]) and DDL/DML (returns affected rows).
"""
from __future__ import annotations

import sqlite3, pathlib, re
from core.workspace import WORKSPACE_ROOT


def _db_path(project_id: str) -> pathlib.Path:
    d = WORKSPACE_ROOT / project_id / ".db"
    d.mkdir(parents=True, exist_ok=True)
    return d / "project.sqlite"


def run_sql(project_id: str, sql: str) -> dict:
    """
    Execute one or more SQL statements.
    Returns:
      {ok, rows, columns, rowcount, error, statements_run}
    """
    db = _db_path(project_id)
    try:
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # Split on semicolons (skip empties)
        stmts = [s.strip() for s in sql.split(";") if s.strip()]
        if not stmts:
            return {"ok": False, "error": "No SQL statements found.",
                    "rows": [], "columns": [], "rowcount": 0, "statements_run": 0}

        rows_out    = []
        columns_out = []
        total_rc    = 0

        for stmt in stmts:
            cur.execute(stmt)
            con.commit()
            total_rc += cur.rowcount if cur.rowcount > 0 else 0
            if cur.description:                # SELECT-like
                columns_out = [d[0] for d in cur.description]
                rows_out    = [dict(row) for row in cur.fetchall()]

        con.close()
        return {
            "ok":             True,
            "rows":           rows_out,
            "columns":        columns_out,
            "rowcount":       total_rc,
            "error":          None,
            "statements_run": len(stmts),
        }

    except sqlite3.Error as e:
        return {
            "ok": False, "error": str(e),
            "rows": [], "columns": [], "rowcount": 0, "statements_run": 0,
        }
    except Exception as e:
        return {
            "ok": False, "error": f"Unexpected error: {e}",
            "rows": [], "columns": [], "rowcount": 0, "statements_run": 0,
        }


def list_tables(project_id: str) -> list[str]:
    """Return all user tables in the project DB."""
    result = run_sql(project_id,
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return [r["name"] for r in result.get("rows", [])]


def describe_table(project_id: str, table: str) -> list[dict]:
    """Return column info for a table: [{cid, name, type, notnull, dflt_value, pk}]"""
    result = run_sql(project_id, f"PRAGMA table_info({table})")
    return result.get("rows", [])
