from __future__ import annotations

import importlib
from typing import TypedDict

import ibis

# Output target `type` -> writer module. Imported on use: each pulls in its
# own heavy deps (dlt, openpyxl, ...).
_WRITERS: dict[str, str] = {
    "json": "json_file",
    "csv": "csv_file",
    "excel": "excel_file",
    "parquet": "parquet",
    "postgres": "postgres",
    "sql_database": "sql_database",
}


class WriteResult(TypedDict):
    rows_written: int
    location: str


def write(
    table: ibis.Table,
    target,
    con: ibis.BaseBackend | None = None,
    credentials: dict | None = None,
    run_id: str | None = None,
) -> WriteResult:
    """`credentials` comes from the destination's linked Connection —
    always a dict (empty `{}` for local file targets).

    All four file formats take credentials now: any of them can address an
    object store, and the writer picks its secret from the URI scheme.
    """
    creds = credentials or {}

    # The destination is the user's; provenance is ours. Split before any
    # writer sees the table so no format has to remember to exclude them.
    if run_id is not None:
        from dte.engine.writers.provenance import split_off_provenance
        table, _ = split_off_provenance(table, run_id, con=con)

    module = _WRITERS.get(getattr(target, "type", None))
    if module is None:
        raise ValueError(f"Unknown output target type: {type(target).__name__}")
    return importlib.import_module(f"dte.engine.writers.{module}").write(table, target, con, creds)


__all__ = ["write", "WriteResult"]
