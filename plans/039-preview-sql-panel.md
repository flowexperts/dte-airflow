# Show compiled SQL in the pipeline preview pane

## Context

Today the builder's right-hand preview (`PipelinePreview`) shows sample rows only — the user has no visibility into what SQL their step configuration actually produces. That gap makes it hard to sanity-check filter expressions, debug an "empty result" pipeline, or learn how the compiler shapes their spec.

Add a **SQL panel** alongside the sample rows so both saved-pipeline dry runs and live (unsaved) previews show the compiled SQL per step + the final SELECT that runs against DuckDB (or the selected engine dialect).

## Approach

Follow the existing `on_step_schema` pattern from plan 038 item 7: a compiler-level callback that captures per-step SQL, wired through the same `/pipelines/dry-run` endpoint that already runs live. No new endpoint — one round-trip serves both data + SQL.

### Backend

**`backend/dte/compiler/ibis_compiler.py`**
- Add `on_step_sql: Callable[[int, str], None] | None = None` to `compile_pipeline`.
- Fire alongside `on_step_schema` after each step succeeds. SQL comes from `ibis.to_sql(registry[current_key], dialect=<dialect>)`.
- Dialect selection: prefer the engine's dialect via a new `BaseEngine.dialect` property (default `"duckdb"`, override to `"trino"` in `TrinoEngine`). Fall back to `"duckdb"` when no engine is passed. Callback wrapped in `try/except` (same defensive pattern as `on_step_schema`).

**`backend/dte/engine/base.py` + `duckdb_engine.py` + `trino_engine.py`**
- Add `dialect: str` class attribute. `"duckdb"` and `"trino"` respectively.

**`backend/dte/api/routes/pipelines.py`**
- Extend `_compile_body_pipeline` to accept + forward `on_step_sql` (mirrors current `on_step_schema` signature).
- Extend `POST /pipelines/dry-run` response: `{rows, count, step_sqls: {str: str}, final_sql: str | None, error: str | null}`.
  - Capture `step_sqls` via the callback (partial capture on compile error, same as step-schemas fix).
  - `final_sql` = `ibis.to_sql(compiled.limit(limit), dialect=…)` (the SELECT that actually executes).
  - Wrap execute in try/except so a runtime failure still returns the SQL captured so far with `error` populated.
- Extend `GET /pipelines/{id}/preview` with the same shape for the saved-pipeline path.

**Tests** (`backend/tests/scenarios/steps/test_dry_run.py`)
- Assert `step_sqls` present with a key per successful step, `final_sql` is a non-empty SELECT.
- Assert partial `step_sqls` are still returned when a later step errors.

### Frontend

**`frontend/src/lib/api.ts`**
- Extend `PreviewResponse` type: `step_sqls?: Record<string, string>; final_sql?: string | null; error?: string | null`.

**`frontend/src/components/pipeline-preview.tsx`**
- Add a small `Segmented` toggle in the section header: **Data | SQL** (default Data). Reuse `Segmented` from the UI kit.
- New `SqlPanel` sub-component (same file — keep it local, one screen of code):
  - If `step_sqls` empty and no `final_sql` → placeholder "SQL will appear once the pipeline compiles."
  - Otherwise render a `Panel` with per-step collapsible entries (labelled `Step 1 · filter`, etc. — pull op names from the pipeline object when available) and a "Final query" block at the bottom.
  - Each SQL block: `<pre className="font-mono text-[11px] bg-code-bg p-3 rounded-sm whitespace-pre-wrap overflow-x-auto">` (matches existing DiffView pattern) with a "Copy" button in the panel head using `navigator.clipboard.writeText`.
- Persist toggle state in component `useState`; no URL/storage.
- Error rendering unchanged; SQL panel shows whatever was captured before the failure.

**No changes** to `BuilderForm`, `SchemaProvider`, editors, or the step-schemas endpoint.

## Files touched

- `backend/dte/compiler/ibis_compiler.py`
- `backend/dte/engine/base.py`, `duckdb_engine.py`, `trino_engine.py`
- `backend/dte/api/routes/pipelines.py`
- `backend/tests/scenarios/steps/test_dry_run.py`
- `frontend/src/lib/api.ts`
- `frontend/src/components/pipeline-preview.tsx`

## Reused primitives (no new deps)

- `ibis.to_sql(table, dialect=...)` — already used in `backend/tests/unit/test_engine_seam.py:138`.
- `on_step_schema` callback pattern — `ibis_compiler.py:113-118`.
- Partial-capture-on-error pattern — the fix just committed for `/pipelines/step-schemas` in `backend/dte/api/routes/pipelines.py:333-352`.
- `Panel`, `PanelHead`, `Segmented`, `Button` from `frontend/src/components/ui/`.
- Code-block styling from `frontend/src/components/builder/history/DiffView.tsx:129-134`.

## Explicitly out of scope

- Syntax highlighting (no `prism`/`highlight.js` in the tree — plain mono).
- Per-engine SQL diffing / dialect toggle in the UI (we serve the engine actually selected on the pipeline).
- Persisting SQL on the `Run` record — this is preview-only.

## Verification

1. Backend unit + scenario: `cd backend && uv run pytest tests/scenarios/steps/test_dry_run.py -m scenario -x -v` — new assertions pass; existing green.
2. Manual: `docker compose up -d --build`, open `/pipelines/new`, pick a source + destination + one filter step, verify:
   - Data toggle → sample rows (existing behaviour).
   - SQL toggle → one collapsible per step + a "Final query" SELECT, all copyable.
   - Break the filter expression → error banner shows AND SQL panel still shows the step(s) that did compile.
3. Regenerate types: from `frontend/` with backend up: `DTE_API_URL=http://localhost:8001 ./scripts/gen-api-types.sh`.
