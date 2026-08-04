from __future__ import annotations

from typing import TypedDict

import ibis

from dte.models.pipeline import (
    CsvTarget,
    ExcelTarget,
    JsonTarget,
    ParquetTarget,
    PostgresTarget,
    SqlDatabaseTarget,
)


class WriteResult(TypedDict):
    rows_written: int
    location: str


def write(
    table: ibis.Table,
    target,
    con: ibis.BaseBackend | None = None,
    credentials: dict | None = None,
) -> WriteResult:
    """`credentials` comes from the destination's linked Connection —
    always a dict (empty `{}` for local file targets).

    All four file formats take credentials now: any of them can address an
    object store, and the writer picks its secret from the URI scheme.
    """
    creds = credentials or {}
    if isinstance(target, JsonTarget):
        from dte.engine.writers import json_file
        return json_file.write(table, target, con, creds)
    if isinstance(target, CsvTarget):
        from dte.engine.writers import csv_file
        return csv_file.write(table, target, con, creds)
    if isinstance(target, ExcelTarget):
        from dte.engine.writers import excel_file
        return excel_file.write(table, target, con, creds)
    if isinstance(target, ParquetTarget):
        from dte.engine.writers import parquet
        return parquet.write(table, target, con, creds)
    if isinstance(target, PostgresTarget):
        from dte.engine.writers import postgres
        return postgres.write(table, target, con, creds)
    if isinstance(target, SqlDatabaseTarget):
        from dte.engine.writers import sql_database
        return sql_database.write(table, target, con, creds)
    raise ValueError(f"Unknown output target type: {type(target).__name__}")


__all__ = ["write", "WriteResult"]
