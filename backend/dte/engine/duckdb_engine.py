from __future__ import annotations

import ibis

from dte.engine.base import BaseEngine
from dte.engine.writers import WriteResult
from dte.engine.writers import write as _write


class RawSqlNotSupportedOnBackend(RuntimeError):
    """Raised when a raw-SQL escape hatch (advanced filter / expression map)
    is used on a table whose native backend isn't DuckDB.

    Raw SQL fragments are DuckDB-dialect and don't translate to
    postgres/bigquery/etc.  Fix: switch that filter to Basic mode, or
    change the pipeline so this step runs on a DuckDB-backed table.
    """


def _is_duckdb_backend(backend: ibis.BaseBackend) -> bool:
    return type(backend).__module__.startswith("ibis.backends.duckdb")


class DuckDBEngine(BaseEngine):
    dialect = "duckdb"

    def __init__(self):
        self._con = ibis.duckdb.connect()

    @property
    def con(self) -> ibis.BaseBackend:
        return self._con

    def execute(self, table: ibis.Table, target, credentials: dict | None = None) -> WriteResult:
        return _write(table, target, self._con, credentials=credentials)

    def apply_filter_sql(self, table: ibis.Table, expr: str) -> ibis.Table:
        _require_duckdb_backend(table, op="filter (Advanced tab)")
        self._con.create_view("_filter_input", table, overwrite=True)
        return self._con.sql(f"SELECT * FROM _filter_input WHERE {expr}")

    def apply_expression_sql(self, table: ibis.Table, output_field: str, expr: str) -> ibis.Table:
        _require_duckdb_backend(table, op="map/expression")
        self._con.create_view("_expr_input", table, overwrite=True)
        return self._con.sql(f"SELECT *, ({expr}) AS {output_field} FROM _expr_input")


def _require_duckdb_backend(table: ibis.Table, op: str) -> None:
    backend = table._find_backend()
    if _is_duckdb_backend(backend):
        return
    dialect = type(backend).__name__
    raise RawSqlNotSupportedOnBackend(
        f"Raw SQL {op} step ran against a {dialect} table, but raw SQL is "
        "DuckDB-dialect only. Switch this step to the Basic tab, or run this "
        "pipeline on a DuckDB-backed source (e.g. export to filesystem first)."
    )
