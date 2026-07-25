# Plan 029 — Data-quality contracts

Covers P2 #23 from `plans/027-p0-p4-status-ladder.md`.

## Problem

Runs today succeed on execution alone — "the SQL ran, `rows_written = N`". Silent bad data (zero rows because upstream broke, duplicate keys, unexpected nulls) surfaces only when a downstream consumer complains days later.

We want declarative expectations attached to a pipeline that run automatically at the end of each successful execution, downgrade run status if violated, and are visible on the run detail page as first-class outcomes.

## Model

Pipeline gains an optional `quality_contracts: list[Contract]` field, discriminated union on `type`:

```python
class RowCountBetween(BaseModel):
    type: Literal["row_count_between"] = "row_count_between"
    id: str            # stable id so results can be joined back
    min: int
    max: int
    severity: Literal["warn", "fail"] = "fail"

class ColumnNotNull(BaseModel):
    type: Literal["column_not_null"] = "column_not_null"
    id: str
    column: str        # dot-syntax, same as step field refs
    severity: Literal["warn", "fail"] = "fail"

class ColumnUnique(BaseModel):
    type: Literal["column_unique"] = "column_unique"
    id: str
    column: str
    severity: Literal["warn", "fail"] = "fail"

class ColumnInRange(BaseModel):
    type: Literal["column_in_range"] = "column_in_range"
    id: str
    column: str
    min: float | None = None
    max: float | None = None
    severity: Literal["warn", "fail"] = "fail"

class ColumnMatches(BaseModel):
    type: Literal["column_matches"] = "column_matches"
    id: str
    column: str
    regex: str
    severity: Literal["warn", "fail"] = "fail"

Contract = Annotated[
    RowCountBetween | ColumnNotNull | ColumnUnique | ColumnInRange | ColumnMatches,
    Field(discriminator="type"),
]
```

## Evaluation seam

Inside `_execute_pipeline` in `dte/api/routes/pipelines.py`, after the writer returns `rows_written` and before setting status to `completed`:

```python
results = await evaluate_contracts(pipeline.quality_contracts, output_target, engine)
await run_store.set_quality(run_id, results)
if any(r.severity == "fail" and not r.passed for r in results):
    status = "failed_quality"
elif any(not r.passed for r in results):
    status = "completed_with_warnings"
else:
    status = "completed"
```

Two new terminal statuses: `completed_with_warnings` and `failed_quality`. Both terminal — `isTerminal()` on the frontend already treats anything non-{pending,running} as terminal, but the type Literal in `Run` needs extending. Alembic trigger `003` needs the new statuses in its `finished_at` set.

Contract execution reuses the shared DuckDB session — writes an intermediate view over the output file if the target is file-based, or queries the target table directly if Postgres.

## Storage

New table `run_quality_results` (Alembic `014_run_quality_results.py`):

```sql
CREATE TABLE run_quality_results (
    run_id       text NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    contract_id  text NOT NULL,
    contract_type text NOT NULL,
    passed       boolean NOT NULL,
    severity     text NOT NULL,           -- 'warn' | 'fail'
    detail       text,                    -- e.g. "5 nulls in 1000 rows"
    evaluated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, contract_id)
);
CREATE INDEX ON run_quality_results (run_id);
```

Not a JSONB column on `runs` — separate table lets us page results and aggregate across runs later (trending is a stretch item, not this plan).

`RunStore` grows `set_quality(run_id, list[QualityResult])` and `get_quality(run_id) -> list[QualityResult]`.

## API

- `GET /api/runs/{id}` — response gains `quality: {passed: int, failed: int, warned: int}` summary counts. Backwards compatible; older clients ignore the field.
- `GET /api/runs/{id}/quality` — full list of contract results for the run.
- `POST /api/pipelines/{id}/quality/dry-run` — evaluate contracts against the *previous* successful run without triggering a new one. Useful for tuning thresholds.

## UI

- `Timeline` on `runs/[id]/page.tsx` gains a "Quality" section below the step timeline. One row per contract: green check / yellow warn / red fail, contract id, one-line detail.
- The pipeline builder gets a `QualityContractsPanel` (new file under `components/builder/quality/`) — a repeatable list of contracts. Reuses `FieldPicker` for column selection.
- Contract editors mirror step editors: one file per contract type, dispatched by discriminator.

## Task list

- `feature/dq-model` — Pydantic contracts + Pipeline field + migration `014`. Compiler untouched.
- `feature/dq-evaluator` — `dte/quality/evaluator.py` running each contract as a DuckDB query. New terminal statuses wired through `Run` model + `MemoryRunStore` + Postgres trigger.
- `feature/dq-api-ui` — routes + Timeline + builder panel.

## Non-goals

- Cross-run trending (a `GET /api/pipelines/{id}/quality/history` endpoint would be great but is out of scope).
- Custom SQL contracts (`ExpressionCheck`) — power move that begs its own plan on sandboxing.
- Alerting on failure (belongs in observability plan 031).

## Rollout

- Ship as opt-in: pipelines without `quality_contracts` behave exactly as today.
- New statuses added incrementally: emit them from the API but leave the UI treatment neutral until the QualityContractsPanel lands.
