# Plan 044: Post-Run Quality Contracts on Transformation Pipelines

## Context

Transformation pipelines produce data. Users want confidence that the data they just produced meets expectations — no unexpected nulls, row counts in range, unique keys, values matching a pattern — without having to build a separate pipeline for it. This plan wires up quality **contracts**: declarative assertions attached to a transformation pipeline, evaluated automatically against the output after each run, surfaced on the run detail page as pass/fail results with counts.

Complementary to plan 043, which introduces a distinct "quality pipeline" type for cases where quality checking IS the job. Plan 044 is for the lightweight case: "I already have a transformation, I just want gates around its output."

## Why this exists as a separate concept

The quality scaffold is **already ~80% built** — no design work needed, just wiring:

- `dte/models/quality.py` — `Contract` discriminated union (`RowCountBetween`, `ColumnNotNull`, `ColumnUnique`, `ColumnInRange`, `ColumnMatches`) + `QualityResult`
- `dte/quality/evaluator.py` — `evaluate_contracts(contracts, target, con)` reads the output file via a temporary DuckDB view and returns per-contract results
- `dte/store/base.py` — `RunStore.set_quality`/`get_quality` declared on the protocol
- `tests/fakes.py` — `FakeRunStore` implements both quality methods plus a `_quality_summary` helper
- `dte/api/routes/runs.py` — `GET /api/runs/{run_id}/quality` endpoint exists and returns `r_store.get_quality(run_id)`
- `Pipeline.quality_contracts` field exists on the pipeline model, validated by `_validate_quality_contracts` (parses raw dicts into typed `Contract` instances)

**What's missing:**
1. The `quality_checks` column on the Postgres `runs` table
2. `PostgresRunStore.set_quality`/`get_quality` implementations
3. The `_run_body()` call site that invokes `evaluate_contracts()` after write
4. New run statuses (`failed_quality`, `completed_with_warnings`) plumbed through the store + frontend
5. UI to define contracts on a pipeline and view results on a run

## Architecture Change

### 1. DB migration 025 — `quality_checks` JSONB column

- **File:** `backend/alembic/versions/025_run_quality_checks.py`
- `down_revision = "024"` (matches the file naming convention of migration 024)
- Follows the `IF NOT EXISTS` + JSONB default pattern from migrations 018–024:

```python
def upgrade() -> None:
    op.execute("""
        ALTER TABLE runs
            ADD COLUMN IF NOT EXISTS quality_checks JSONB NOT NULL DEFAULT '[]'::jsonb
    """)

def downgrade() -> None:
    op.execute("ALTER TABLE runs DROP COLUMN IF EXISTS quality_checks")
```

No backfill needed — default is empty array, existing runs stay valid.

### 2. `PostgresRunStore.set_quality`/`get_quality`

- **File:** `backend/dte/store/postgres.py`
- Add two methods to `PostgresRunStore`:

```python
async def set_quality(self, run_id: str, results: list) -> None:
    serialised = [r.model_dump() if hasattr(r, "model_dump") else r for r in results]
    async with _open_tenant_session(self._factory) as s:
        await s.execute(
            text("UPDATE runs SET quality_checks = CAST(:v AS jsonb) WHERE id = :id"),
            {"v": json.dumps(serialised), "id": run_id},
        )
        await s.commit()

async def get_quality(self, run_id: str) -> list:
    async with _open_tenant_session(self._factory) as s:
        result = await s.execute(
            text("SELECT quality_checks FROM runs WHERE id = :id"),
            {"id": run_id},
        )
        row = result.mappings().fetchone()
        return list(row["quality_checks"] or []) if row else []
```

- The existing `PostgresRunStore.get()` and `list_for_pipeline()` methods use hard-coded SELECT lists — extend both to include `quality_checks` so the quality summary flows through to `GET /api/runs/{id}` responses.
- Move `_quality_summary` helper (currently in `tests/fakes.py`) to `dte/quality/summary.py` and import it from both `FakeRunStore` and `PostgresRunStore`. Contract: given `list[QualityResult | dict]`, return `{total, passed, failed, warnings, pass_rate}` dict.

### 3. Wire `evaluate_contracts()` into `_run_body()`

- **File:** `backend/dte/api/routes/pipelines.py`
- After the existing `write` tracing span (around line 868) completes and before the final `r_store.update(run_id, status="completed", ...)`:

```python
with tr.start_as_current_span("quality") as q_span:
    contracts = getattr(pipeline, "quality_contracts", []) or []
    quality_results = []
    if contracts:
        from dte.quality.evaluator import evaluate_contracts
        quality_results = evaluate_contracts(contracts, destination.config, engine.con)
        q_span.set_attribute("contracts_evaluated", len(contracts))
        q_span.set_attribute("contracts_passed", sum(1 for r in quality_results if r.passed))
    await r_store.set_quality(run_id, [r.model_dump() for r in quality_results])

failed_hard = any(not r.passed and r.severity == "fail" for r in quality_results)
failed_warn = any(not r.passed and r.severity == "warn" for r in quality_results)
final_status = (
    "failed_quality" if failed_hard
    else "completed_with_warnings" if failed_warn
    else "completed"
)
await r_store.update(run_id, status=final_status, rows_written=result["rows_written"], location=result["location"])
```

`evaluate_contracts` is synchronous and shares the ibis DuckDB backend already used by `engine.execute()` — no thread hop, no new connection.

### 4. New run statuses

- **File:** `backend/dte/store/base.py`
- Extend `RunStatus` literal (if declared) to include `"failed_quality"` and `"completed_with_warnings"`. Both are **terminal** statuses.
- **File:** `backend/tests/fakes.py`
- `FakeRunStore.update()` already accepts arbitrary status strings — verify a test exercises the new values so a future stricter typing doesn't silently break.

### 5. Frontend — contracts builder on pipeline edit

- **File (new):** `frontend/src/components/builder/QualityContractsPanel.tsx`
- Collapsible `Panel` rendered by `BuilderForm` below `StepsPanel`
- Displays `pipeline.quality_contracts` as a list of rows
- Per-row UI: contract type dropdown (5 types) + column picker (`FieldPicker`) when column-scoped + params (min/max, regex) + severity toggle (warn/fail) + remove button
- "Add contract" button appends a new row with sensible defaults
- Contracts shape matches the backend `Contract` discriminated union — the `type` field drives which params inputs render

- **File:** `frontend/src/components/builder/BuilderForm.tsx`
- Include `quality_contracts` in the form state; POST/PUT sends it to the backend as-is (backend validator coerces raw dicts to typed `Contract` instances)

### 6. Frontend — run detail quality panel

- **File:** `frontend/src/lib/api.ts`
- Add `QualityCheckResult` interface: `{ contract_id: string; contract_type: string; passed: boolean; severity: "warn" | "fail"; detail: string | null }`
- Extend `Run` type with `quality?: { total: number; passed: number; failed: number; warnings: number; pass_rate: number } | null`
- Update `RunStatus` union: `"pending" | "running" | "completed" | "failed" | "failed_quality" | "completed_with_warnings"`
- Update `isTerminal()` to include the two new terminal statuses — **critical**, otherwise the run-detail page polls forever on quality-failed runs
- Add `getRunQuality(run_id)` helper: `apiFetch<{results: QualityCheckResult[]; count: number}>('/api/runs/{run_id}/quality')`

- **File:** `frontend/src/app/(app)/runs/[id]/page.tsx`
- Add a SWR query for `getRunQuality(id)` that fires only when `isTerminal(status)` and the run has `quality.total > 0`
- Add a quality `<Metric>` to the existing `MetricRow`: value = `${Math.round(pass_rate * 100)}%`, tone = `ok`|`warn`|`err` based on pass rate
- Add a quality section (`SectionHead` + `DataTable`) after the existing Timeline:
  - Columns: Contract type, Column (if applicable), Status (`Pill`), Detail
  - Row tone reflects `passed && severity`
- Handle `"failed_quality"` and `"completed_with_warnings"` in the `pillStatus` helper and the error panel header

### 7. Frontend — quality column on runs list

- **File:** `frontend/src/components/runs-table.tsx` (or wherever the recent-runs table lives)
- Add a "Quality" column rendering a `Pill`:
  - 100% pass → `status="ok"`, label `"100%"`
  - Any warn or partial → `status="running"` (gold tone), label `"{pass_rate}%"`
  - Any hard fail → `status="failed"`, label `"{pass_rate}%"`
  - No contracts → em-dash

## Task List

| # | Task | Files | Branch |
|---|---|---|---|
| 1 | Migration 025 — `quality_checks` column | `alembic/versions/025_run_quality_checks.py` | `feature/044-1-migration` |
| 2 | `PostgresRunStore` quality methods + SELECT list updates + shared `_quality_summary` | `dte/store/postgres.py`, `dte/quality/summary.py` | `feature/044-2-store-quality` |
| 3 | Wire `evaluate_contracts()` + new statuses into `_run_body()` | `dte/api/routes/pipelines.py` | `feature/044-3-run-body` |
| 4 | New run statuses in base + fakes tests | `dte/store/base.py`, `tests/fakes.py` | `feature/044-4-statuses` |
| 5 | `QualityContractsPanel` + wire into `BuilderForm` | `components/builder/QualityContractsPanel.tsx`, `BuilderForm.tsx` | `feature/044-5-contracts-ui` |
| 6 | Run detail quality panel + `isTerminal` fix + API types | `lib/api.ts`, `app/(app)/runs/[id]/page.tsx` | `feature/044-6-run-detail` |
| 7 | Quality column on runs list | `components/runs-table.tsx` | `feature/044-7-runs-list` |

## Critical Files

- `backend/alembic/versions/025_run_quality_checks.py` (new)
- `backend/dte/store/postgres.py` — quality methods + SELECT list updates
- `backend/dte/quality/summary.py` (new) — shared summary helper
- `backend/dte/api/routes/pipelines.py` — evaluate_contracts wiring
- `frontend/src/components/builder/QualityContractsPanel.tsx` (new)
- `frontend/src/lib/api.ts` — types + `isTerminal` fix
- `frontend/src/app/(app)/runs/[id]/page.tsx` — quality panel

## Files Deleted

None — this is purely additive.

## Test Plan

### Unit
- `tests/unit/test_quality_evaluator.py`: existing tests continue to pass — no changes to `evaluate_contracts` API
- `tests/unit/test_quality_summary.py` (new): shared `_quality_summary` helper edge cases (empty list, all pass, all fail, mixed)
- `tests/unit/test_pipeline_spec.py`: quality_contracts serialization/deserialization round-trip

### Integration
- `tests/integration/test_store_postgres.py`: `PostgresRunStore.set_quality`/`get_quality` round-trip against real Postgres (auto-skips when `DATABASE_URL` unset)

### Scenario
- `tests/scenarios/test_quality_contracts.py` (new):
  - `test_all_contracts_pass_completes_ok` — pipeline with 2 passing contracts → status "completed", quality API returns 2 passed results
  - `test_hard_contract_fail_downgrades_status` — `column_not_null` fail=severity → status "failed_quality"
  - `test_warn_contract_fail_marks_warnings` — `column_not_null` warn=severity → status "completed_with_warnings"
  - `test_pipeline_without_contracts_completes_normally` — no contracts → status "completed", quality API returns empty list
  - `test_run_detail_response_includes_quality_summary` — `GET /api/runs/{id}` embeds the quality summary dict

## Verification

1. `uv run pytest tests/unit -k "quality"` — passes
2. `DATABASE_URL=... uv run alembic upgrade head` — migration 025 applies cleanly
3. `DATABASE_URL=... uv run pytest tests/integration/test_store_postgres.py -k "quality"` — passes
4. `uv run pytest tests/scenarios/test_quality_contracts.py -m scenario -v` — passes
5. Frontend: open an existing pipeline, add a `column_not_null` contract via the new panel, trigger the pipeline against data with nulls, confirm the run detail page shows a red quality section and the runs list shows a red quality pill

## Risks & Gotchas

1. **`isTerminal()` must include new statuses.** If `"failed_quality"` and `"completed_with_warnings"` are missing from the frontend's `isTerminal`, the run detail page polls forever on those runs. Test this explicitly.

2. **`PostgresRunStore.get()` hard-coded SELECT list.** The `get()` method (around line 114) selects named columns explicitly — `quality_checks` must be added there and in `list_for_pipeline()` or the API silently returns null quality data even after it's stored.

3. **`evaluate_contracts` I/O against the output file.** It reads the file that was just written via a DuckDB view. For large outputs and many contracts, this can be slow. Add a warning log if quality evaluation exceeds 10% of total run elapsed time; long-term, consider evaluating against the in-memory ibis table before write.

4. **`_run_body` timeout budget.** The `asyncio.wait_for` in `_execute_pipeline` (around line 758) wraps everything including quality evaluation. Very large datasets + many contracts could hit the timeout. Document this and consider a separate quality-eval timeout in a future plan.

5. **Contracts against `postgres` / `sql_database` destinations.** `evaluate_contracts` currently only supports file-based targets (json_file, csv_file, excel_file, parquet_s3) — see the `NotImplementedError` branch in `_view_sql_for_target`. Contracts on DB destinations either need to be rejected at save time (422) or the evaluator extended. Recommendation: reject at save time in this plan; extend in a follow-up.

6. **Contract validation on save.** `PipelineBase._validate_quality_contracts` currently parses contracts but does not validate columns exist on the source or that contracts are compatible with the destination type. Consider adding a soft validation pass (warn only, don't block) — otherwise misspelled column names surface only at run time as opaque DuckDB errors.

7. **Coordination with plan 043.** Plan 043 (quality pipeline type) depends on the migration and store methods in this plan. Land plan 044 first; plan 043 reuses the same `quality_checks` column and store methods.
