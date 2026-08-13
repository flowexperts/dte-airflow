from __future__ import annotations

from itertools import count

import ibis

from dte.engine.base import BaseEngine, EnrichmentSpec
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
        self._view_seq = count()

    @property
    def con(self) -> ibis.BaseBackend:
        return self._con

    def execute(self, table: ibis.Table, target, credentials: dict | None = None, run_id: str | None = None) -> WriteResult:
        return _write(table, target, self._con, credentials=credentials, run_id=run_id)

    def apply_filter_sql(self, table: ibis.Table, expr: str) -> ibis.Table:
        _require_duckdb_backend(table, op="filter (Advanced tab)")
        view_name = f"_filter_input_{next(self._view_seq)}"
        self._con.create_view(view_name, table, overwrite=True)
        return self._con.sql(f"SELECT * FROM {view_name} WHERE {expr}")

    def apply_expression_sql(self, table: ibis.Table, output_field: str, expr: str) -> ibis.Table:
        _require_duckdb_backend(table, op="map/expression")
        view_name = f"_expr_input_{next(self._view_seq)}"
        self._con.create_view(view_name, table, overwrite=True)
        return self._con.sql(f"SELECT *, ({expr}) AS {output_field} FROM {view_name}")

    def apply_enrichment(
        self, table: ibis.Table, spec: EnrichmentSpec
    ) -> ibis.Table:
        """Materialise, map every row in Python, register the result back.

        The laziness break documented on `EnrichmentSpec`. Each mapper result
        is merged *over* the input row, so upstream columns survive; returning
        several dicts fans the row out, returning none drops it.

        Results go into a real table rather than a view — the mapper has
        already been paid for, and a view would re-run nothing but would let
        the name outlive the data it describes.
        """
        import pyarrow as pa

        rows = table.to_pyarrow().to_pylist()

        out_rows: list[dict] = []
        for row in rows:
            for produced in spec.mapper(row):
                out_rows.append({**row, **produced})

        name = f"_enrich_{spec.name}_{next(self._view_seq)}"

        if out_rows:
            arrow = pa.Table.from_pylist(out_rows)
        else:
            # Nothing survived. Build an empty table with the right columns so
            # downstream steps see a schema instead of a missing-column error.
            empty = {c: [] for c in table.columns}
            empty.update({c: [] for c in spec.output_schema})
            arrow = pa.Table.from_pydict(empty)

        self._con.con.register(name, arrow)
        return self._con.table(name)


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
