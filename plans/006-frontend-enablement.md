# Plan 006 — Frontend Enablement (CORS + Pipeline CRUD)

## Problem

The frontend planned in 002/004 cannot call the API from `http://localhost:3000` (or Vite's `:5173`) because no CORS middleware is configured. Additionally, the pipeline builder needs to save edits and delete pipelines, but `dte/api/routes/pipelines.py` only exposes create / list / get / preview / trigger — no `PUT` or `DELETE`.

## Architecture

### CORS
- Add `fastapi.middleware.cors.CORSMiddleware` in `dte/api/main.py`.
- Origins read from env var `DTE_CORS_ORIGINS` (comma-separated); default `http://localhost:3000,http://localhost:5173`.
- Allow methods `*`, headers `*`, credentials `True`.

### Pipeline update
- `PUT /api/pipelines/{id}` — full replace. Body is a `Pipeline`. 404 if id missing. Returns the updated pipeline.
- `PipelineStore` gains `update(pipeline: Pipeline) -> Pipeline`. `MemoryStore` overwrites the dict entry; `PostgresStore` runs an `UPDATE ... RETURNING *`.

### Pipeline delete
- `DELETE /api/pipelines/{id}` — 204 on success, 404 if missing.
- Cascade runs: `RunStore.delete_for_pipeline(pipeline_id)` invoked before the pipeline is deleted (memory: filter dict; postgres: `DELETE FROM runs WHERE pipeline_id = ...`).
- `PipelineStore.delete(pipeline_id) -> bool` returns True if a row was removed.

## Tasks

### Task 1 — CORS middleware
- Branch: `feature/api-cors`
- Modify `dte/api/main.py`
- Test first: `tests/unit/test_api_cors.py`
  - `test_cors_preflight_allows_localhost_3000` — OPTIONS request with `Origin: http://localhost:3000` returns 200 with `Access-Control-Allow-Origin`
  - `test_cors_custom_origin_from_env` — monkeypatch `DTE_CORS_ORIGINS`, assert new origin allowed

### Task 2 — Pipeline update / delete
- Branch: `feature/api-pipeline-crud`
- Extend `PipelineStore` protocol and both implementations
- Add `RunStore.delete_for_pipeline` in both implementations
- Add routes to `dte/api/routes/pipelines.py`
- Test first: `tests/unit/test_api_pipelines.py`
  - `test_update_pipeline_replaces_definition`
  - `test_update_missing_pipeline_returns_404`
  - `test_delete_pipeline_returns_204`
  - `test_delete_missing_pipeline_returns_404`
  - `test_delete_cascades_runs`

## Response shapes

```
PUT /api/pipelines/{id}
Body: Pipeline JSON
→ Pipeline JSON (200)

DELETE /api/pipelines/{id}
→ 204 No Content
```

## Files changed
- `dte/api/main.py` — CORSMiddleware
- `dte/api/routes/pipelines.py` — PUT, DELETE
- `dte/store/base.py` — protocol methods
- `dte/store/memory.py` — implementations
- `dte/store/postgres.py` — implementations
- `tests/unit/test_api_cors.py` — new
- `tests/unit/test_api_pipelines.py` — new (or extend if exists)

## What does NOT change
- `dte/compiler/`, `dte/engine/`, `dte/sources/`, `dte/models/`
- No alembic migration needed (no schema change)
