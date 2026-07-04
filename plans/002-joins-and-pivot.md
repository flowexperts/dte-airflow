# Plan 002 — Joins and Pivot

## Problem

The compiler handles single-source pipelines only. `compile_pipeline()` always starts from `tables[pipeline.sources[0].id]`. Joins (multi-source merge) and pivot (reshape rows to columns) are missing, making DTE unable to express most real-world transformations.

## Architecture change

### Join

A `JoinStep` references two named tables by source id or by an alias assigned to a prior step result. The compiler must maintain a named table registry (`dict[str, ibis.Table]`) instead of a single rolling `table` variable. Each step can optionally write its result into the registry under a given `id`.

```
tables registry: {source_id: ibis.Table, ...}
    ↓ each step reads from registry[input] and writes to registry[output]
final step output → execute
```

For Phase 2: keep it simple — `JoinStep.left` and `JoinStep.right` are source ids (or prior step `output_id`s). No DAG editor yet.

### Pivot

Ibis has no native pivot. Fall through to DuckDB SQL using `PIVOT` syntax (DuckDB supports it natively since 0.8). Strategy: `create_view` + `con.sql("PIVOT ...")` — same pattern as filter/expression steps.

## Step models to add (`dte/models/pipeline.py`)

```python
class JoinStep(BaseModel):
    op: Literal["join"]
    left: str           # source id or output_id of a prior step
    right: str          # source id or output_id of a prior step
    on: str | list[str] # column(s) to join on
    how: Literal["inner", "left", "right", "outer"] = "inner"
    output_id: str      # register result under this id for downstream steps

class PivotStep(BaseModel):
    op: Literal["pivot"]
    index: str | list[str]   # columns to keep as rows
    columns: str              # column whose values become new column names
    values: str               # column to aggregate into pivoted cells
    agg: Literal["sum", "count", "avg", "min", "max"] = "sum"
```

`UnpivotStep` is out of scope for this plan.

## Compiler changes (`dte/compiler/ibis_compiler.py`)

Replace the rolling `table` variable with a registry:

```python
def compile_pipeline(pipeline, tables):
    registry = dict(tables)   # {id: ibis.Table}

    for step in pipeline.steps:
        op = step["op"]
        if op == "join":
            s = JoinStep(**step)
            left = registry[s.left]
            right = registry[s.right]
            result = _apply_join(left, right, s)
            registry[s.output_id] = result
        elif op == "pivot":
            # pivot always operates on the "current" table
            # current table = last registered result that isn't a named source
            table = _current(registry, pipeline)
            table = _apply_pivot(table, PivotStep(**step), ...)
        else:
            # existing single-table steps operate on _current(registry, pipeline)
            table = _current(registry, pipeline)
            table = _apply_existing_step(table, step)
            registry["__current__"] = table

    return _current(registry, pipeline)
```

`_current()` returns `registry["__current__"]` if present, else `registry[pipeline.sources[0].id]`.

### Join implementation

```python
def _apply_join(left, right, step):
    on_cols = [step.on] if isinstance(step.on, str) else step.on
    predicates = [left[c] == right[c] for c in on_cols]
    return left.join(right, predicates, how=step.how)
```

ibis deduplicates overlapping column names with suffixes — document this behaviour.

### Pivot implementation

```python
def _apply_pivot(table, step, con):
    con.create_view("_dte_pivot_input", table, overwrite=True)
    index = ", ".join([step.index] if isinstance(step.index, str) else step.index)
    return con.sql(f"""
        PIVOT _dte_pivot_input
        ON {step.columns}
        USING {step.agg}({step.values})
        GROUP BY {index}
    """)
```

## Tasks

### Task 1 — JoinStep model + compiler
- Branch: `feature/join-step`
- Write `tests/unit/test_compiler.py::test_join_inner`, `test_join_left`, `test_join_on_multiple_columns`
- Add `JoinStep` to `pipeline.py`
- Implement `_apply_join` and registry pattern in compiler
- Run `pytest tests/unit/test_compiler.py -x`

### Task 2 — PivotStep model + compiler
- Branch: `feature/pivot-step`
- Write `tests/unit/test_compiler.py::test_pivot_sum`, `test_pivot_count`
- Add `PivotStep` to `pipeline.py`
- Implement `_apply_pivot`
- Run `pytest tests/unit/test_compiler.py -x`

### Task 3 — Integration tests for join + pivot
- Branch: `feature/join-pivot-integration`
- `test_end_to_end_join_two_sources` — two JSON files, inner join, write output
- `test_end_to_end_pivot` — JSON with category+amount rows, pivot to columns
- Run `pytest tests/integration/ -x`

## Files changed
- `dte/models/pipeline.py` — add JoinStep, PivotStep
- `dte/compiler/ibis_compiler.py` — registry pattern, _apply_join, _apply_pivot
- `tests/unit/test_compiler.py` — new join + pivot tests
- `tests/unit/test_pipeline_spec.py` — new model tests
- `tests/integration/test_execution.py` — new end-to-end tests

## What does NOT change
- `dte/sources/dlt_loader.py`
- `dte/engine/duckdb_engine.py`
- `dte/schema/inferrer.py`
- `dte/api/`
