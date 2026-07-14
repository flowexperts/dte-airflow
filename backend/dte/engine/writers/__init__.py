from __future__ import annotations
from typing import TypedDict
import ibis
from dte.models.pipeline import (
    JsonFileTarget,
    CsvFileTarget,
    ParquetS3Target,
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
    always a dict (empty `{}` for local file targets)."""
    creds = credentials or {}
    if isinstance(target, JsonFileTarget):
        from dte.engine.writers import json_file
        return json_file.write(table, target, con)
    if isinstance(target, CsvFileTarget):
        from dte.engine.writers import csv_file
        return csv_file.write(table, target, con)
    if isinstance(target, ParquetS3Target):
        from dte.engine.writers import parquet_s3
        return parquet_s3.write(table, target, con, creds)
    if isinstance(target, PostgresTarget):
        from dte.engine.writers import postgres
        return postgres.write(table, target, con, creds)
    if isinstance(target, SqlDatabaseTarget):
        from dte.engine.writers import sql_database
        return sql_database.write(table, target, con, creds)
    raise ValueError(f"Unknown output target type: {type(target).__name__}")


__all__ = ["write", "WriteResult"]
