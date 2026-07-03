from __future__ import annotations
import ibis
import ibis.expr.datatypes as dt
import ibis.expr.types as et
from dte.models.pipeline import (
    Pipeline, FilterStep, RenameStep, RetypeStep,
    LookupMapStep, ExpressionMapStep, SortStep,
    AggregateStep, AggSpec, OutputField,
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
    # Try struct traversal first
    if parts[0] in table.columns:
        col = table[parts[0]]
        for part in parts[1:]:
            col = col[part]
        return col
    # Fall back to dlt-normalized double-underscore column name
    dlt_name = "__".join(parts)
    if dlt_name in table.columns:
        return table[dlt_name]
    return table[field_path]


def compile_pipeline(pipeline: Pipeline, tables: dict[str, ibis.Table]) -> ibis.Table:
    table = tables[pipeline.sources[0].id]

    for step in pipeline.steps:
        op = step["op"]
        if op == "filter":
            table = _apply_filter(table, FilterStep(**step))
        elif op == "rename":
            table = _apply_rename(table, RenameStep(**step))
        elif op == "retype":
            table = _apply_retype(table, RetypeStep(**step))
        elif op == "map":
            mode = step["mode"]
            if mode == "lookup":
                table = _apply_lookup(table, LookupMapStep(**step))
            else:
                table = _apply_expression(table, ExpressionMapStep(**step))
        elif op == "sort":
            table = _apply_sort(table, SortStep(**step))
        elif op == "aggregate":
            table = _apply_aggregate(table, AggregateStep(**step))

    if pipeline.output.fields:
        table = _apply_output_fields(table, pipeline.output.fields)

    return table


def _apply_filter(table: ibis.Table, step: FilterStep) -> ibis.Table:
    con = table._find_backend()
    view_name = "_dte_filter_input"
    con.create_view(view_name, table, overwrite=True)
    return con.sql(f"SELECT * FROM {view_name} WHERE {step.expr}")


def _apply_rename(table: ibis.Table, step: RenameStep) -> ibis.Table:
    # ibis rename takes {new_name: old_name}
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
