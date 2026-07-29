from __future__ import annotations

from typing import TYPE_CHECKING

import ibis
import ibis.expr.datatypes as dt

from dte.errors import CompilerError
from dte.models.pipeline import (
    AggregateStep,
    DatePartGroupBy,
    ExpressionMapStep,
    FilterStep,
    JoinStep,
    LookupMapStep,
    LookupTable,
    OutputField,
    Pipeline,
    PivotStep,
    RenameStep,
    RetypeStep,
    SelectStep,
    SortStep,
)

if TYPE_CHECKING:
    from dte.engine.base import BaseEngine


class MixedBackendError(CompilerError):
    """Raised when a pipeline's source tables span multiple ibis backends.

    Ibis can't execute a join across two live backends without materialising
    one side.  In the DTE architecture, sources on the same Connection.id
    share a backend (via :class:`BackendRegistry`), so a pipeline with two
    postgres tables on the same connection is fine, but joining a postgres
    table with a filesystem CSV (or with a bigquery table) trips this
    error.  Fix: split into two pipelines, or opt into ``engine="trino"``
    to federate.
    """

    def __init__(self, source_backends: dict[str, str]):
        self.source_backends = source_backends
        engines = sorted(set(source_backends.values()))
        super().__init__(
            f"Pipeline sources span multiple ibis backends ({engines}). "
            "Cross-backend joins aren't supported without a federator. "
            "Split into single-backend pipelines, or set engine='trino'."
        )

_TYPE_MAP: dict[str, dt.DataType] = {
    "string": dt.String(),
    "int": dt.Int64(),
    "float": dt.Float64(),
    "boolean": dt.Boolean(),
    "date": dt.Date(),
    "timestamp": dt.Timestamp(),
}


def _check_single_backend(tables: dict[str, ibis.Table]) -> None:
    """Reject pipelines whose source tables live on more than one ibis
    backend.  See :class:`MixedBackendError` for the rationale.

    Tables from the same connection share a backend instance (BackendRegistry
    guarantees this by caching), so identity comparison via ``id(backend)`` is
    reliable — no false positives from two DuckDB connections that look alike.
    """
    if not tables:
        return
    per_source: dict[str, tuple[int, str]] = {}
    for sid, tbl in tables.items():
        backend = tbl._find_backend()
        per_source[sid] = (id(backend), type(backend).__name__)
    unique = {bid for bid, _ in per_source.values()}
    if len(unique) > 1:
        raise MixedBackendError({sid: name for sid, (_, name) in per_source.items()})


def _resolve_field(table: ibis.Table, field_path: str) -> ibis.Expr:
    parts = field_path.split(".")
    if parts[0] in table.columns:
        col = table[parts[0]]
        for part in parts[1:]:
            col = col[part]
        return col
    dlt_name = "__".join(parts)
    if dlt_name in table.columns:
        return table[dlt_name]
    if field_path in table.columns:
        return table[field_path]
    raise CompilerError(
        f"unknown field {field_path!r}; available columns: {sorted(table.columns)}"
    )


def compile_pipeline(
    pipeline: Pipeline,
    tables: dict[str, ibis.Table],
    output=None,
    lookup_tables: dict[str, LookupTable] | None = None,
    on_step=None,
    engine: BaseEngine | None = None,
    on_step_schema=None,
    on_step_sql=None,
) -> ibis.Table:
    """Compile a pipeline into an ibis expression.

    `on_step(step_index, op, status, message=None)` — optional sync callback
    invoked with `status="started"` before each step and `status="completed"`
    or `status="failed"` after. Callers use this to persist per-step events
    without threading async into the compiler.

    `engine` — optional engine instance (plan-034).  When supplied, raw-SQL
    escape hatches (filter / expression-map) are routed through
    ``engine.apply_filter_sql`` / ``engine.apply_expression_sql`` so the
    engine can apply backend-specific behaviour (e.g. Trino rejecting raw
    DuckDB SQL).  When ``None`` (default) the existing ``table._find_backend()``
    path is used — backwards-compatible for all existing callers.

    `on_step_schema(step_index, columns)` — optional sync callback fired
    after each step compiles successfully with the list of column names
    on the current-key table.  Feeds ``/api/pipelines/step-schemas`` so
    the frontend can offer autocomplete on aggregation aliases and pivot
    outputs downstream (plan 038 item 7).

    `on_step_sql(step_index, sql)` — optional sync callback fired after
    each step compiles successfully with the SQL that materialises the
    current-key table.  SQL is rendered via ``ibis.to_sql`` using the
    engine's dialect (defaulting to ``duckdb`` when no engine is
    supplied).  Feeds the preview SQL panel (plan-039).
    """
    registry = dict(tables)
    _check_single_backend(registry)
    lookups = lookup_tables or {}
    current_key = pipeline.sources[0]

    def _emit(idx, op, status, msg=None):
        if on_step is not None:
            try:
                on_step(idx, op, status, msg)
            except Exception:  # never let telemetry crash a run
                pass

    for idx, step in enumerate(pipeline.steps):
        op = step["op"]
        _emit(idx, op, "started")
        try:
            if op == "join":
                s = JoinStep(**step)
                result = _apply_join(registry[s.left], registry[s.right], s)
                registry[s.output_id] = result
                current_key = s.output_id
            else:
                table = registry[current_key]
                table = _dispatch_single_table_step(table, step, lookups, engine=engine)
                registry[current_key] = table
        except Exception as e:
            _emit(idx, op, "failed", str(e))
            raise
        _emit(idx, op, "completed")
        if on_step_schema is not None:
            try:
                cols = list(registry[current_key].columns)
                on_step_schema(idx, cols)
            except Exception:  # never let telemetry crash a run
                pass
        if on_step_sql is not None:
            try:
                dialect = getattr(engine, "dialect", "duckdb")
                sql = str(ibis.to_sql(registry[current_key], dialect=dialect))
                on_step_sql(idx, sql)
            except Exception:  # never let telemetry crash a run
                pass

    result = registry[current_key]
    fields = getattr(output, "fields", None)
    if fields:
        result = _apply_output_fields(result, fields)
    return result


def _dispatch_single_table_step(
    table: ibis.Table,
    step: dict,
    lookup_tables: dict[str, LookupTable],
    engine: BaseEngine | None = None,
) -> ibis.Table:
    op = step["op"]
    if op == "filter":
        return _apply_filter(table, FilterStep(**step), engine=engine)
    elif op == "rename":
        return _apply_rename(table, RenameStep(**step))
    elif op == "retype":
        return _apply_retype(table, RetypeStep(**step))
    elif op == "map":
        mode = step["mode"]
        if mode == "lookup":
            return _apply_lookup(table, LookupMapStep(**step), lookup_tables)
        else:
            return _apply_expression(table, ExpressionMapStep(**step), engine=engine)
    elif op == "sort":
        return _apply_sort(table, SortStep(**step))
    elif op == "aggregate":
        return _apply_aggregate(table, AggregateStep(**step))
    elif op == "pivot":
        return _apply_pivot(table, PivotStep(**step))
    elif op == "select":
        s = SelectStep(**step)
        if s.drop:
            drop_set = set(s.drop)
            keep = [c for c in table.columns if c not in drop_set]
            return table.select(keep)
        return _apply_output_fields(table, s.fields)
    raise CompilerError(f"unknown step op {op!r}")


def _apply_join(left: ibis.Table, right: ibis.Table, step: JoinStep) -> ibis.Table:
    on_cols = [step.on] if isinstance(step.on, str) else step.on
    predicates = [left[c] == right[c] for c in on_cols]
    # ibis suffixes duplicate column names with _right when both tables share the same column name
    return left.join(right, predicates, how=step.how)


def _apply_pivot(table: ibis.Table, step: PivotStep) -> ibis.Table:
    con = table._find_backend()
    con.create_view("_dte_pivot_input", table, overwrite=True)
    index = ", ".join([step.index] if isinstance(step.index, str) else step.index)
    # con.sql() fails (sqlglot can't subquery PIVOT); dynamic PIVOT can't be a view in DuckDB.
    # Materialise into a temp table via the raw connection, then read back through ibis.
    con.con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _dte_pivot_result AS
        PIVOT _dte_pivot_input
        ON {step.columns}
        USING {step.agg}({step.values})
        GROUP BY {index}
    """)
    return con.table("_dte_pivot_result")


def _apply_filter(
    table: ibis.Table,
    step: FilterStep,
    engine: BaseEngine | None = None,
) -> ibis.Table:
    """Apply a raw SQL WHERE-clause fragment.

    When *engine* is supplied the call routes through
    ``engine.apply_filter_sql`` so each backend can handle portability
    (e.g. Trino raises ``TrinoRawSqlNotSupported``).  Without an engine
    the legacy ``table._find_backend()`` path is used — no behaviour change
    for existing DuckDB-only callers.
    """
    if engine is not None:
        return engine.apply_filter_sql(table, step.expr)
    con = table._find_backend()
    view_name = "_dte_filter_input"
    con.create_view(view_name, table, overwrite=True)
    return con.sql(f"SELECT * FROM {view_name} WHERE {step.expr}")


def _apply_rename(table: ibis.Table, step: RenameStep) -> ibis.Table:
    unknown = [old for old in step.mappings if old not in table.columns]
    if unknown:
        raise CompilerError(
            f"rename: unknown source field(s) {unknown!r}; "
            f"available columns: {sorted(table.columns)}"
        )
    return table.rename({v: k for k, v in step.mappings.items()})


def _apply_retype(table: ibis.Table, step: RetypeStep) -> ibis.Table:
    # to_type is Literal-validated on RetypeStep, so unknown values never reach
    # here. Field name isn't — check it and raise a typed error.
    if step.field not in table.columns:
        raise CompilerError(
            f"retype: unknown field {step.field!r}; available columns: {sorted(table.columns)}"
        )
    ibis_type = _TYPE_MAP[step.to_type]
    return table.cast({step.field: ibis_type})


def _apply_lookup(
    table: ibis.Table,
    step: LookupMapStep,
    lookup_tables: dict[str, LookupTable],
) -> ibis.Table:
    if step.lookup_id not in lookup_tables:
        raise CompilerError(f"map/lookup: unknown lookup_id {step.lookup_id!r}")
    lt = lookup_tables[step.lookup_id]
    col = _resolve_field(table, step.field)
    cases = [(col == k, ibis.literal(v)) for k, v in lt.mappings.items()]
    default = ibis.literal(lt.default) if lt.default is not None else None
    expr = ibis.cases(*cases, else_=default)
    # Struct paths can't be mutated in place; the output column takes the
    # leaf name at the top level of the resulting table (unless output_field
    # is explicitly set).
    out_name = step.output_field or (
        step.field.split(".")[-1] if "." in step.field else step.field
    )
    return table.mutate(**{out_name: expr})


def _apply_expression(
    table: ibis.Table,
    step: ExpressionMapStep,
    engine: BaseEngine | None = None,
) -> ibis.Table:
    """Add a computed column via raw SQL expression.

    When *engine* is supplied the call routes through
    ``engine.apply_expression_sql`` so each backend can handle portability.
    Without an engine the legacy ``table._find_backend()`` path is used.
    """
    if engine is not None:
        return engine.apply_expression_sql(table, step.output_field, step.expr)
    con = table._find_backend()
    view_name = "_dte_expr_input"
    con.create_view(view_name, table, overwrite=True)
    return con.sql(
        f'SELECT *, ({step.expr}) AS "{step.output_field}" FROM {view_name}'
    )


def _apply_sort(table: ibis.Table, step: SortStep) -> ibis.Table:
    ascending = step.ascending
    if isinstance(ascending, bool):
        ascending = [ascending] * len(step.by)

    order_exprs = []
    for col, asc in zip(step.by, ascending, strict=False):
        expr = _resolve_field(table, col)
        order_exprs.append(ibis.asc(expr) if asc else ibis.desc(expr))

    return table.order_by(order_exprs)


def _apply_aggregate(table: ibis.Table, step: AggregateStep) -> ibis.Table:
    agg_exprs = []
    for agg in step.aggregations:
        col = _resolve_field(table, agg.field)
        if agg.func == "sum":
            expr = col.sum()
        elif agg.func == "count":
            expr = col.count()
        elif agg.func == "avg":
            expr = col.mean()
        elif agg.func == "min":
            expr = col.min()
        elif agg.func == "max":
            expr = col.max()
        elif agg.func == "count_distinct":
            expr = col.nunique()
        agg_exprs.append(expr.name(agg.alias))

    group_by_exprs = [_resolve_group_by(table, g) for g in step.group_by]
    return table.group_by(group_by_exprs).aggregate(agg_exprs)


def _resolve_group_by(table: ibis.Table, entry: str | DatePartGroupBy) -> ibis.Expr:
    if isinstance(entry, str):
        return _resolve_field(table, entry).name(entry)
    # DatePartGroupBy — extract a temporal component.
    col = _resolve_field(table, entry.field)
    col_type = col.type()
    if not (col_type.is_timestamp() or col_type.is_date()):
        raise CompilerError(
            f"aggregate group_by part={entry.part!r} requires a date/timestamp field; "
            f"{entry.field!r} is {col_type}"
        )
    part = entry.part
    if part == "year":
        expr = col.year()
    elif part == "quarter":
        expr = col.quarter()
    elif part == "month":
        expr = col.month()
    elif part == "week":
        expr = col.week_of_year()
    elif part == "day":
        expr = col.day()
    elif part == "date":
        # Truncate timestamp to date; dates stay as-is.
        expr = col.date() if col_type.is_timestamp() else col
    elif part == "dow":
        expr = col.day_of_week.index()
    elif part == "hour":
        if not col_type.is_timestamp():
            raise CompilerError(
                f"aggregate group_by part='hour' requires a timestamp; "
                f"{entry.field!r} is {col_type}"
            )
        expr = col.hour()
    else:  # pragma: no cover — Literal guard
        raise CompilerError(f"unknown date part {part!r}")
    alias = entry.alias or f"{entry.field.split('.')[-1]}_{part}"
    return expr.name(alias)


def _apply_output_fields(table: ibis.Table, fields: list[OutputField]) -> ibis.Table:
    selections = []
    for f in fields:
        col = _resolve_field(table, f.field)
        if f.alias:
            col = col.name(f.alias)
        elif "." in f.field:
            # struct traversal — give the projected column a stable name
            # from the leaf segment rather than a compiler-generated one.
            col = col.name(f.field.split(".")[-1])
        selections.append(col)
    return table.select(selections)
