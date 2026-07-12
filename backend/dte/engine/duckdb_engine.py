from __future__ import annotations
import ibis
from dte.engine.base import BaseEngine
from dte.engine.writers import write as _write, WriteResult


class DuckDBEngine(BaseEngine):
    def __init__(self):
        self._con = ibis.duckdb.connect()

    @property
    def con(self) -> ibis.BaseBackend:
        return self._con

    def execute(self, table: ibis.Table, target) -> WriteResult:
        return _write(table, target, self._con)

    def apply_filter_sql(self, table: ibis.Table, expr: str) -> ibis.Table:
        self._con.create_view("_filter_input", table, overwrite=True)
        return self._con.sql(f"SELECT * FROM _filter_input WHERE {expr}")

    def apply_expression_sql(self, table: ibis.Table, output_field: str, expr: str) -> ibis.Table:
        self._con.create_view("_expr_input", table, overwrite=True)
        return self._con.sql(f"SELECT *, ({expr}) AS {output_field} FROM _expr_input")
