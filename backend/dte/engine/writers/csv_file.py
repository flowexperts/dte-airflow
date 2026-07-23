from __future__ import annotations

import ibis

from dte.models.pipeline import CsvFileTarget


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def write(table: ibis.Table, target: CsvFileTarget, con: ibis.BaseBackend | None = None) -> dict:
    """Stream to disk via DuckDB's native COPY.

    Delegates serialisation to DuckDB — the previous implementation buffered
    the whole frame through pandas which fell over on multi-GB result sets.
    """
    backend = table._find_backend()
    backend.create_view("_dte_csv_output", table, overwrite=True)
    (count,) = backend.con.execute("SELECT COUNT(*) FROM _dte_csv_output").fetchone()
    backend.con.execute(
        f"COPY _dte_csv_output TO {_sql_str(target.path)} (FORMAT CSV, HEADER)"
    )
    return {"rows_written": int(count), "location": target.path}
