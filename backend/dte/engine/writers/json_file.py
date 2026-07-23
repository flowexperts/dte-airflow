from __future__ import annotations

import ibis

from dte.models.pipeline import JsonFileTarget


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def write(table: ibis.Table, target: JsonFileTarget, con: ibis.BaseBackend | None = None) -> dict:
    """Stream to disk via DuckDB's native COPY.

    Delegates serialisation to DuckDB so we never materialise the full result
    set in Python memory. Preserves the previous JSON array shape (matches
    what the frontend `RunOutputPreview` and `runs/{id}/output` reader expect).
    """
    backend = table._find_backend()
    backend.create_view("_dte_json_output", table, overwrite=True)
    (count,) = backend.con.execute("SELECT COUNT(*) FROM _dte_json_output").fetchone()
    backend.con.execute(
        f"COPY _dte_json_output TO {_sql_str(target.path)} (FORMAT JSON, ARRAY true)"
    )
    return {"rows_written": int(count), "location": target.path}
