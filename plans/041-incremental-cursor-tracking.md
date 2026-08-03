# Incremental loading: cursor / high-watermark tracking

## Problem

Trigger-time params (plan 040) let an orchestrator pass a window explicitly, but the orchestrator still has to know what value to pass. For true "ingest only new records" behaviour the engine itself should remember where it left off — the max value of a designated cursor column after the last successful run — and automatically filter to records beyond that point on the next run.

This is the standard high-watermark / incremental-load pattern used by dlt, Airbyte, and Fivetran. It trades full-refresh simplicity for O(new rows) cost on every scheduled run.

## Scope

- Each **source** (not pipeline) declares an optional `incremental_key: str | None` — the column whose max value acts as the cursor (typically `updated_at`, `created_at`, `id`).
- The engine records `cursor_value: str | None` on the `Run` after each successful execution.
- On next trigger, if the source has an `incremental_key` and a previous successful run exists with a `cursor_value`, the engine injects a `WHERE <cursor_column> > <last_cursor>` filter before any user-authored steps.
- A full-refresh escape hatch: `POST /api/pipelines/{id}/trigger` with `{"full_refresh": true}` skips cursor injection entirely.

## Architecture change

### Source model

`Source` gains one nullable field:

```python
incremental_key: str | None = None
```

`SourceBase` validation: if set, must be a non-empty string. No existence check at save time (schema isn't always known). Alembic `011` adds the column.

### Run model + store

`Run` gains two nullable fields:

```python
cursor_value: str | None = None   # serialised as ISO-8601 string for dates; str(int) for ints
cursor_source_id: str | None = None  # which source this cursor belongs to
```

Alembic `012` adds both columns. `PostgresRunStore` exposes a new query method:

```python
async def last_successful_cursor(self, pipeline_id: str, source_id: str) -> str | None:
    """Return cursor_value from the most recent completed run for this pipeline+source pair."""
```

This is a single indexed SELECT — `(pipeline_id, source_id, status, finished_at DESC)` partial index on `runs`. Add that index in migration `012`.

### Cursor injection in `_execute_pipeline`

Before `compile_pipeline`, for each source in the pipeline:
1. Fetch `Source` from `SourceStore`.
2. If `source.incremental_key` is set and `full_refresh` is not requested:
   a. Call `run_store.last_successful_cursor(pipeline_id, source.id)`.
   b. If a previous cursor exists, prepend a synthetic filter step to that source's table in the compiler context (see below).
3. After successful execution, compute the new cursor: `SELECT MAX(<incremental_key>) FROM <final_table>` via DuckDB and write it to `Run.cursor_value` + `Run.cursor_source_id`.

**Synthetic filter injection**: The compiler's named registry already holds one `ibis.Table` per source before user steps run. Cursor injection adds a `.filter(table[incremental_key] > cursor_value)` call on that table immediately after loading and before the step chain begins. This is invisible to the user's step list.

The `incremental_key` column type determines how the cursor is compared:
- Temporal (`date`, `timestamp`, `timestamptz`): cast cursor string to the column's dtype via ibis `.cast()`.
- Integer / bigint: `int(cursor_value)`.
- String: direct string comparison (lexicographic — user's responsibility to use a sortable format like ISO-8601 or zero-padded IDs).

Type detection uses `ibis_table.schema()[incremental_key].name` at injection time. Unknown types fall back to string comparison with a warning logged.

### Trigger endpoint

`TriggerRequest` (from plan 040) gains one more optional field:

```python
full_refresh: bool = False
```

When `True`, cursor injection is skipped for all sources. The run still writes a new `cursor_value` so the next regular run picks up from where the full refresh ended (not from the previous incremental cursor). This is the correct default — a full refresh intentionally advances the watermark.

### Multi-source pipelines

Each source in `pipeline.sources` is evaluated independently. If the pipeline joins two sources and both have `incremental_key`, both get their own cursor injection and the run stores the cursor for the primary source (the one listed first, or the one with the largest `current_key` at the end of compilation — TBD, keep it simple: first source wins for now). This is a known simplification; multi-cursor tracking can be added later.

## Data model

```
sources
  + incremental_key  text nullable

runs
  + cursor_value      text nullable   -- serialised max value of the cursor column
  + cursor_source_id  text nullable   -- source.id this cursor belongs to

Index: runs(pipeline_id, cursor_source_id, status, finished_at DESC) WHERE status = 'completed'
```

Alembic `011_source_incremental_key.py` and `012_run_cursor.py`.

## API surface changes

```
POST /api/sources
PUT  /api/sources/{id}
  body: SourceBase { ..., incremental_key?: string | null }

GET /api/sources/{id}
  response: Source { ..., incremental_key?: string | null }

GET /api/runs/{run_id}
  response: Run { ..., cursor_value?: string | null, cursor_source_id?: string | null }

POST /api/pipelines/{id}/trigger
  body: TriggerRequest { params?: dict, full_refresh?: bool }
  (extends plan 040)
```

## Frontend

### Source editor — incremental key field

In `SourceEditor.tsx` (and each per-kind editor), add an optional **Incremental key** `Field` + `Input` below the existing config fields. Placeholder: `e.g. updated_at`. Helper text: "If set, each run filters to rows where this column exceeds the previous run's maximum value."

If `SchemaProvider` has fields for this source, replace the `Input` with a `FieldPicker` so authors can pick a column by name. Gracefully degrade to plain `Input` when schema is unavailable (source not yet saved or schema not inferred).

### Run detail — cursor display

On `runs/[id]/page.tsx`, if `run.cursor_value` is non-null, add a `MetricRow` entry:

```
Cursor   updated_at > 2024-07-30T23:59:59
```

Format: `<source.incremental_key> > <cursor_value>`. Fetch source name from the pipeline's source list to make it readable. Show "Full refresh" label instead when triggered with `full_refresh: true` (detectable if `cursor_value` is non-null but params contained `full_refresh: true` — store that flag on the run record too, see below).

Add `full_refresh: bool = False` to `Run` model and `runs` table (migration `012` covers it) so the UI can label the run accurately without inferring from params.

### Trigger modal (extends plan 040 TriggerModal)

Add a **Full refresh** toggle (default off). When on, a warning note: "Ignores the cursor — all source rows are processed. The new cursor will advance to the latest value found."

## Files touched

**Backend**
- `dte/models/pipeline.py` — `Source.incremental_key`, `Run.cursor_value`, `Run.cursor_source_id`, `Run.full_refresh`
- `dte/sources/loader.py` — no change (cursor injection happens post-load in the API layer)
- `dte/compiler/ibis_compiler.py` — accept optional `cursor_filters: dict[str, ibis.Expr] | None` applied to the initial registry before user steps
- `dte/api/routes/pipelines.py` — `TriggerRequest.full_refresh`, cursor fetch + inject + write logic in `_execute_pipeline`
- `dte/store/base.py` — `RunStore.last_successful_cursor()` method on the protocol
- `dte/store/postgres.py` — implement `last_successful_cursor` + partial index
- `backend/alembic/versions/011_source_incremental_key.py` (new)
- `backend/alembic/versions/012_run_cursor.py` (new)
- `tests/unit/test_cursor_injection.py` (new) — unit test the ibis filter injection path
- `tests/scenarios/test_incremental.py` (new) — end-to-end: first run ingests all rows + writes cursor; second run ingests only new rows (assert row counts + cursor values)

**Frontend**
- `src/lib/api.ts` — `Source.incremental_key`, `Run.cursor_value`, `Run.cursor_source_id`, `Run.full_refresh`
- `src/components/builder/sources/SourceEditor.tsx` — incremental key field
- `src/components/pipeline-detail/TriggerModal.tsx` — full refresh toggle (extends plan 040)
- `src/app/(app)/runs/[id]/page.tsx` — cursor MetricRow

## Out of scope

- Multi-cursor tracking (one watermark per source per pipeline — punted to a follow-up).
- Cursor persistence across pipeline renames or source swaps. If the source `incremental_key` changes, the previous cursor is stale — user should trigger a full refresh.
- UI to view or reset the cursor outside of triggering a full refresh.
- dlt-based sources (`mongodb`, `rest_api`) — dlt has its own state management. The injected filter would duplicate dlt's internal cursor. These source kinds should skip cursor injection (guard on `source.source_type in {"mongodb", "rest_api"}`).

## Dependency

Plan 040 (trigger-time params) should be merged first — this plan extends `TriggerRequest` and `TriggerModal`. The backend cursor logic is independent of param interpolation but the modal and run-record shape build on those foundations.

## Verification

1. Unit: `cd backend && uv run pytest tests/unit/test_cursor_injection.py -x`
2. Scenario:
   ```bash
   cd backend && uv run pytest tests/scenarios/test_incremental.py -m scenario -x -v
   ```
   - Run 1: source has 10 rows, `incremental_key=created_at`. Run completes, `cursor_value` = max `created_at`.
   - Run 2: source now has 12 rows (2 new). Run completes with 2 rows written; `cursor_value` advances.
   - Run 3 (full refresh): all 12 rows processed. `full_refresh=true` on run record.
3. Manual:
   - Set `incremental_key` on a filesystem JSON source. Trigger twice. Confirm second run's row count < first run's.
   - Trigger with full refresh. Confirm all rows processed and cursor advances.
   - Pipeline with a source that has no `incremental_key` — confirm no filter injected, behaves as today.
