from __future__ import annotations

from itertools import count

import ibis
import pyarrow as pa

from dte.engine.base import BaseEngine, EnrichmentSpec
from dte.engine.writers import WriteResult
from dte.engine.writers import write as _write


class RawSqlNotSupportedOnBackend(RuntimeError):
    """Raised by a backend that cannot take a raw-SQL fragment at all.

    Kept for engines with no SQL-string seam (see TrinoEngine). The SQL
    backends do not raise it: `Table.alias(...).sql(..., dialect="duckdb")`
    transpiles the fragment through sqlglot to whatever dialect the table's
    own backend speaks.
    """


# `EnrichmentSpec.output_schema` SQL type names → Arrow. JSON columns are
# carried as encoded strings (see the `*_meta` columns).
_ARROW_TYPES = {
    "VARCHAR": pa.string(), "JSON": pa.string(), "BIGINT": pa.int64(),
    "INTEGER": pa.int32(), "DOUBLE": pa.float64(), "BOOLEAN": pa.bool_(),
    "TIMESTAMP": pa.timestamp("us"), "DATE": pa.date32(),
}


class DuckDBEngine(BaseEngine):
    dialect = "duckdb"

    def __init__(self):
        self._con = ibis.duckdb.connect()
        self._view_seq = count()

    @property
    def con(self) -> ibis.BaseBackend:
        return self._con

    def execute(self, table: ibis.Table, target, credentials: dict | None = None, run_id: str | None = None) -> WriteResult:
        # Pass our connection only when the table lives in it. A natively-bound
        # table (postgres source) must reach the writer's Arrow-staging path,
        # which a DuckDB `con` would skip (plan 086).
        con = self._con if table._find_backend() is self._con else None
        return _write(table, target, con, credentials=credentials, run_id=run_id)

    # Raw SQL rides on the table's OWN backend via a CTE alias, not on a view
    # created in self._con. Two things follow, and both were bugs before:
    # the fragment is transpiled from DuckDB dialect by sqlglot, so a filter
    # or map/expression step runs unchanged against Postgres/MySQL/etc; and
    # nothing is written to the user's database to make it work.
    def apply_filter_sql(self, table: ibis.Table, expr: str) -> ibis.Table:
        name = f"_filter_input_{next(self._view_seq)}"
        return table.alias(name).sql(
            f"SELECT * FROM {name} WHERE {expr}", dialect=self.dialect,
        )

    def apply_expression_sql(self, table: ibis.Table, output_field: str, expr: str) -> ibis.Table:
        name = f"_expr_input_{next(self._view_seq)}"
        return table.alias(name).sql(
            f'SELECT *, ({expr}) AS "{output_field}" FROM {name}', dialect=self.dialect,
        )

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
        src = table.to_pyarrow()
        rows = src.to_pylist()

        out_rows: list[dict] = []
        for row in rows:
            for produced in spec.mapper(row):
                out_rows.append({**row, **produced})

        name = f"_enrich_{spec.name}_{next(self._view_seq)}"

        # Known types: the input's own, overlaid with what the step declares.
        # Inferring from Python values instead turned an empty input, or a
        # column NULL in every row, into int32 — and a writer then created
        # timestamp/text destination columns as integer.
        declared = {f.name: f.type for f in src.schema}
        declared.update({c: _ARROW_TYPES.get(t.upper(), pa.string())
                         for c, t in spec.output_schema.items()})

        if out_rows:
            arrow = pa.Table.from_pylist(out_rows)
            for i, f in enumerate(arrow.schema):
                if pa.types.is_null(f.type) and f.name in declared:
                    arrow = arrow.set_column(i, f.name, arrow.column(i).cast(declared[f.name]))
        else:
            # Nothing survived: an empty table with the right columns and
            # types, so downstream steps see a schema, not a missing column.
            arrow = pa.Table.from_pydict(
                {c: pa.array([], type=t) for c, t in declared.items()})

        self._con.con.register(name, arrow)
        return self._con.table(name)
