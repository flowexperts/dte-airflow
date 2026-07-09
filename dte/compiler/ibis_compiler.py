from __future__ import annotations
import ibis
import ibis.expr.datatypes as dt
import ibis.expr.types as et
from dte.models.pipeline import (
    Pipeline, FilterStep, RenameStep, RetypeStep,
    LookupMapStep, ExpressionMapStep, SortStep,
    AggregateStep, AggSpec, OutputField, JoinStep, PivotStep,
)

_TYPE_MAP: dict[str, dt.DataType] = {
    "string": dt.String(),
    "int": dt.Int64(),
    "float": dt.Float64(),
    "boolean": dt.Boolean(),
    "date": dt.Date(),
    "timestamp": dt.Timestamp(),
}


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
    return table[field_path]


def compile_pipeline(pipeline: Pipeline, tables: dict[str, ibis.Table]) -> ibis.Table:
    registry = dict(tables)
    current_key = pipeline.sources[0].id

    for step in pipeline.steps:
        op = step["op"]
        if op == "join":
            s = JoinStep(**step)
            result = _apply_join(registry[s.left], registry[s.right], s)
            registry[s.output_id] = result
            current_key = s.output_id
        else:
            table = registry[current_key]
            table = _dispatch_single_table_step(table, step)
            registry[current_key] = table

    result = registry[current_key]
    fields = getattr(pipeline.output, "fields", None)
    if fields:
        result = _apply_output_fields(result, fields)
    return result


def _dispatch_single_table_step(table: ibis.Table, step: dict) -> ibis.Table:
    op = step["op"]
    if op == "filter":
        return _apply_filter(table, FilterStep(**step))
    elif op == "rename":
        return _apply_rename(table, RenameStep(**step))
    elif op == "retype":
        return _apply_retype(table, RetypeStep(**step))
    elif op == "map":
        mode = step["mode"]
        if mode == "lookup":
            return _apply_lookup(table, LookupMapStep(**step))
        else:
            return _apply_expression(table, ExpressionMapStep(**step))
    elif op == "sort":
        return _apply_sort(table, SortStep(**step))
    elif op == "aggregate":
        return _apply_aggregate(table, AggregateStep(**step))
    elif op == "pivot":
        return _apply_pivot(table, PivotStep(**step))
    return table


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
    con.con.execute("""
        CREATE OR REPLACE TEMP TABLE _dte_pivot_result AS
        PIVOT _dte_pivot_input
        ON {columns}
        USING {agg}({values})
        GROUP BY {index}
    """.format(columns=step.columns, agg=step.agg, values=step.values, index=index))
    return con.table("_dte_pivot_result")


def _apply_filter(table: ibis.Table, step: FilterStep) -> ibis.Table:
    con = table._find_backend()
    view_name = "_dte_filter_input"
    con.create_view(view_name, table, overwrite=True)
    return con.sql(f"SELECT * FROM {view_name} WHERE {step.expr}")


def _apply_rename(table: ibis.Table, step: RenameStep) -> ibis.Table:
    return table.rename({v: k for k, v in step.mappings.items()})


def _apply_retype(table: ibis.Table, step: RetypeStep) -> ibis.Table:
    ibis_type = _TYPE_MAP[step.to_type]
    return table.cast({step.field: ibis_type})


def _apply_lookup(table: ibis.Table, step: LookupMapStep) -> ibis.Table:
    col = table[step.field]
    cases = [(col == k, ibis.literal(v)) for k, v in step.table.items()]
    default = ibis.literal(step.default) if step.default is not None else None
    expr = ibis.cases(*cases, else_=default)
    return table.mutate(**{step.field: expr})


def _apply_expression(table: ibis.Table, step: ExpressionMapStep) -> ibis.Table:
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
    for col, asc in zip(step.by, ascending):
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

    group_by_exprs = [_resolve_field(table, f).name(f) for f in step.group_by]
    return table.group_by(group_by_exprs).aggregate(agg_exprs)


def _apply_output_fields(table: ibis.Table, fields: list[OutputField]) -> ibis.Table:
    selections = []
    for f in fields:
        col = table[f.field]
        if f.alias:
            col = col.name(f.alias)
        selections.append(col)
    return table.select(selections)
