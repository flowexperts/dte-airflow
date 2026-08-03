# Plan 043: Data Quality Pipeline Type

## Context

DTE today is a Data **Transformation** Engine — every step mutates data flowing through the pipeline, and the output is a transformed dataset. We want to add a distinct "quality pipeline" concept where the entire pipeline exists to **assert conditions on data** rather than transform it. Data passes through unchanged; the output is a **quality report** (rows per check with column, rule, total, failed count, pass rate).

Complementary to this plan: plan 044 adds post-run quality contracts to existing transformation pipelines (a lighter-weight approach for adding quality gates to data you're already producing). Plan 043 is for the case where quality checking IS the job.

## Why a new pipeline type?

The step abstraction is fundamentally different:

| | Transform step | Check step |
|---|---|---|
| **Mutates data** | Yes (filter drops rows, rename changes names) | No — always pass-through |
| **Can fail?** | Only on compile errors | On row-level violations |
| **Purpose** | Produce clean data | Report on data quality |

Trying to fold check semantics into the existing step dispatcher creates the "is drop a filter or a quality action?" ambiguity we hit earlier. Making pipeline type a first-class field resolves the ambiguity cleanly.

## Architecture Change

### 1. Pipeline type discriminator

- **File:** `backend/dte/models/pipeline.py`
- Add to `PipelineBase`:
  ```python
  pipeline_type: Literal["transform", "quality"] = "transform"
  ```
- Existing pipelines default to "transform" — zero back-compat impact.
- `_validate_steps` validator gains a branch: when `pipeline_type == "quality"`, allow existing transformation ops (filter, rename, retype, sort, select, join) **plus** new check ops. Aggregate/pivot are disallowed in quality pipelines (they change grain and make check semantics unclear).

### 2. New check step ops

All check steps are pass-through: they emit a `QualityResult` via a callback and return the input table unchanged.

```python
class CheckNotNullStep(BaseModel):
    op: Literal["check_not_null"]
    column: str
    severity: Literal["warn", "fail"] = "fail"

class CheckUniqueStep(BaseModel):
    op: Literal["check_unique"]
    column: str
    severity: Literal["warn", "fail"] = "fail"

class CheckRangeStep(BaseModel):
    op: Literal["check_range"]
    column: str
    min: float | None = None
    max: float | None = None
    severity: Literal["warn", "fail"] = "fail"

class CheckRegexStep(BaseModel):
    op: Literal["check_regex"]
    column: str
    pattern: str
    severity: Literal["warn", "fail"] = "fail"

class CheckAcceptedValuesStep(BaseModel):
    op: Literal["check_accepted_values"]
    column: str
    values: list[str | int | float]
    severity: Literal["warn", "fail"] = "fail"

class CheckRowCountStep(BaseModel):
    op: Literal["check_row_count"]
    min: int | None = None
    max: int | None = None
    severity: Literal["warn", "fail"] = "fail"

class CheckCustomSqlStep(BaseModel):
    op: Literal["check_custom_sql"]
    sql: str  # WHERE clause that should match ZERO rows for pass
    label: str  # human-readable name
    severity: Literal["warn", "fail"] = "fail"

class ProfileStep(BaseModel):
    op: Literal["profile"]
    columns: list[str] = Field(default_factory=list)  # empty = all columns
```

Register each in `_STEP_MODELS`.

### 3. Compiler handlers

- **File:** `backend/dte/compiler/ibis_compiler.py`
- Add `on_quality_result: Callable[[int, QualityResult], None] | None = None` to `compile_pipeline()`
- Add dispatch cases for each check op — each calls a `_apply_check_*()` handler that:
  1. Materializes the current ibis table to a temp view (reuse the `_create_quality_view` pattern from `dte/quality/evaluator.py`)
  2. Runs a scalar COUNT query for the violation condition
  3. Builds a `QualityResult` and calls `on_quality_result(step_index, result)`
  4. Returns the table **unchanged**
- Violation SQL per rule (same as plan 044's `evaluate_contracts`, but run inline):
  - `check_not_null`: `SELECT COUNT(*) FROM v WHERE "col" IS NULL`
  - `check_unique`: `SELECT SUM(cnt - 1) FROM (SELECT COUNT(*) cnt FROM v GROUP BY "col" HAVING cnt > 1)`
  - `check_range`: `SELECT COUNT(*) FROM v WHERE "col" < min OR "col" > max`
  - `check_regex`: `SELECT COUNT(*) FROM v WHERE NOT regexp_matches("col", 'pattern')`
  - `check_accepted_values`: `SELECT COUNT(*) FROM v WHERE "col" NOT IN (values)`
  - `check_row_count`: `SELECT COUNT(*) FROM v` then compare to bounds
  - `check_custom_sql`: `SELECT COUNT(*) FROM v WHERE ({sql})`

### 4. Quality report as run output

Quality pipelines don't write to a data destination. Instead, `_run_body()` in `pipelines.py` branches on `pipeline.pipeline_type`:

- `"transform"`: existing behavior — resolve destination, compile, execute, write
- `"quality"`: resolve source(s), compile with `on_quality_result` callback collecting results, skip destination write, call `r_store.set_quality(run_id, results)`

`Pipeline.output_id` becomes **optional** when `pipeline_type == "quality"` (add a model validator: output_id required iff type is transform).

Run status computation for quality pipelines:
```python
failed_hard = any(not r.passed and r.severity == "fail" for r in results)
failed_warn = any(not r.passed and r.severity == "warn" for r in results)
final_status = (
    "failed_quality"       if failed_hard
    else "completed_with_warnings" if failed_warn
    else "completed"
)
```

(Depends on plan 044's migration 025 for the `quality_checks` column and `PostgresRunStore.set_quality`/`get_quality` implementation — plan 044 must land first.)

### 5. Frontend — quality pipeline mode

- **File:** `frontend/src/components/builder/BuilderForm.tsx`
- Add pipeline type toggle at the top (`Segmented` component: "Transform" / "Quality")
- When type is "quality":
  - Step palette shows only quality-compatible steps (filter, rename, select, join, plus all check_* ops)
  - Destination picker is hidden (replaced with "Output: quality report on the run")
  - `output_id` is not required for form validation

- **File:** `frontend/src/components/builder/steps/types.ts`
- Add all check op names to `StepOp` union + `STEP_OPS` array with a `category: "transform" | "quality"` field
- Filter `STEP_OPS` by category based on active pipeline type in `StepsPanel`

- **File:** `frontend/src/components/builder/steps/editors.tsx`
- One editor per check op — each is simple: column picker (`FieldPicker`) + rule-specific params (min/max, pattern, values, sql) + severity toggle
- `CheckRowCountEditor`: min/max number inputs, no column picker
- `ProfileEditor`: `FieldMultiSelect` for columns

### 6. Frontend — quality report view

- **File:** `frontend/src/app/(app)/runs/[id]/page.tsx`
- When run's pipeline is quality-type, replace the output-preview section with a **Quality Report** panel:
  - `DataTable` with columns: Step index, Check type, Column, Status (Pill), Total rows, Failed rows, Pass rate, Detail
  - Summary `MetricRow` at top: total checks, passed, failed, warnings, overall pass rate
- Transform-type runs keep existing output-preview behavior

## Task List

| # | Task | Files | Branch |
|---|---|---|---|
| 1 | Add `pipeline_type` field to `PipelineBase` + validator | `dte/models/pipeline.py` | `feature/043-1-pipeline-type` |
| 2 | Add all check step models + register in `_STEP_MODELS` | `dte/models/pipeline.py` | `feature/043-2-check-step-models` |
| 3 | Compiler handlers for check_* + profile with `on_quality_result` callback | `dte/compiler/ibis_compiler.py` | `feature/043-3-check-handlers` |
| 4 | Branch `_run_body()` on pipeline_type; collect inline quality results | `dte/api/routes/pipelines.py` | `feature/043-4-quality-run-body` |
| 5 | Pipeline type toggle + conditional destination in `BuilderForm` | `frontend/src/components/builder/BuilderForm.tsx` | `feature/043-5-builder-mode` |
| 6 | Check step editors + category filtering | `steps/types.ts`, `steps/editors.tsx`, `steps/StepsPanel.tsx` | `feature/043-6-check-editors` |
| 7 | Quality report view on run detail | `app/(app)/runs/[id]/page.tsx` | `feature/043-7-quality-report-view` |

## Critical Files

- `backend/dte/models/pipeline.py` — pipeline type field + check step models + `_validate_steps` branch
- `backend/dte/compiler/ibis_compiler.py` — check step dispatch + `on_quality_result` callback
- `backend/dte/api/routes/pipelines.py` — `_run_body()` branches on pipeline_type
- `frontend/src/components/builder/BuilderForm.tsx` — pipeline type toggle
- `frontend/src/components/builder/steps/editors.tsx` — new check editors
- `frontend/src/app/(app)/runs/[id]/page.tsx` — quality report view

## Files Deleted

None — this is purely additive.

## Test Plan

### Unit
- `tests/unit/test_pipeline_spec.py`: quality-type pipeline accepts check_* ops; rejects aggregate/pivot; output_id optional for quality type
- `tests/unit/test_compiler.py`: each `_apply_check_*` handler with a hand-built ibis table — verify (a) table returned unchanged, (b) `on_quality_result` called with correct QualityResult, (c) counts accurate
- `tests/unit/test_check_step_models.py` (new): Pydantic validation of each check step model

### Scenario
- `tests/scenarios/steps/test_quality_pipeline.py` (new):
  - `test_all_checks_pass_run_completed` — quality pipeline where all checks pass → status "completed", quality results stored
  - `test_hard_check_fail_downgrades_status` — a `check_not_null` (severity=fail) with nulls → status "failed_quality"
  - `test_warn_check_fail_marks_warnings` — check with severity=warn fails → status "completed_with_warnings"
  - `test_multiple_checks_run_independently` — one failing check does not prevent others from running
  - `test_profile_step_captures_stats` — profile step results in the quality report

### Integration
- Build a quality pipeline via `POST /api/pipelines` with `pipeline_type: "quality"`, no `output_id`, three check steps; trigger it; verify `GET /api/runs/{id}/quality` returns three results

## Verification

1. `uv run pytest tests/unit -k "check or quality"` — all unit tests pass
2. `uv run pytest tests/scenarios/steps/test_quality_pipeline.py -m scenario -v` — scenarios pass
3. Frontend: create a quality pipeline in the builder, add three check steps, trigger, verify quality report renders with correct pass/fail counts

## Risks & Gotchas

1. **Depends on plan 044** for the `quality_checks` DB column and store methods. Plan 044 must land first (or its migration + store changes are pulled into this plan as a prerequisite).

2. **Trino incompatibility** — check handlers use raw DuckDB SQL. Guard against `TrinoEngine` at the top of each `_apply_check_*` handler and raise `CompilerError` with a clear message.

3. **Materialization overhead** — every check step re-materializes the table to a temp view. For pipelines with many checks against the same data, this is wasteful. Optimization (future): if consecutive steps are all checks, share one materialization.

4. **`output_id` optional-when-quality** — the discriminated union at the API layer must accept quality pipelines without `output_id`. Any code path that assumes `pipeline.output_id` is set (`_compile_body_pipeline`, preview endpoint, dry-run) must branch or reject quality pipelines.

5. **Preview / dry-run for quality pipelines** — what does preview show? Recommendation: for quality pipelines, `POST /api/pipelines/{id}/dry-run` returns the quality report (same as a full run but without persisting); preview endpoint is disabled with a 400.

6. **Frontend step palette filtering** — the `Add step` menu must hide check_* ops when in transform mode and hide aggregate/pivot when in quality mode. If a user toggles pipeline type on an existing pipeline with incompatible steps, warn before saving.

7. **Run detail page — one page, two views** — the same `runs/[id]/page.tsx` renders both transform and quality runs. The page currently assumes a data output; add a `pipelineType` fetch and branch the middle sections.
