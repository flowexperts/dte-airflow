from __future__ import annotations
import json
from pathlib import Path
import ibis
from dte.engine.base import BaseEngine


class DuckDBEngine(BaseEngine):
    def __init__(self):
        self._con = ibis.duckdb.connect()

    @property
    def con(self) -> ibis.BaseBackend:
        return self._con

    def execute_to_json(self, table: ibis.Table, output_path: str) -> int:
        df = table.execute()
        records = df.to_dict(orient="records")
        Path(output_path).write_text(json.dumps(records, default=str, indent=2))
        return len(records)

    def apply_filter_sql(self, table: ibis.Table, expr: str) -> ibis.Table:
        self._con.create_view("_filter_input", table, overwrite=True)
        return self._con.sql(f"SELECT * FROM _filter_input WHERE {expr}")

    def apply_expression_sql(self, table: ibis.Table, output_field: str, expr: str) -> ibis.Table:
        self._con.create_view("_expr_input", table, overwrite=True)
        return self._con.sql(f"SELECT *, ({expr}) AS {output_field} FROM _expr_input")
