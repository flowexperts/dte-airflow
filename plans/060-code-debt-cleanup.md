# Plan 060: Code Debt Cleanup

## Problem Statement

Ponytail ultra audit identified 25 incremental simplifications and deletions across frontend and backend: dead code, back-compat shims past their expiration, refactored-away helpers still exported, duplicated CRUD patterns, and an unused dependency. None block a feature; each removes a small maintenance surface or clarifies an API contract. Combined: **1,630 lines deleted, 1 dep removed**. The work is mechanical and low-risk — each piece is independently verifiable by grep, AST scan, or import trace.

## Architecture Changes

No architecture changes — this is pure debt reduction. The changes cluster into five themes:

1. **Delete expired one-off migrations and feature scaffolds** (plans 015, 028, 036, 037, 046).
2. **Delete back-compat shims and aliases past their "one release"** window.
3. **Delete dead symbols** — never raised, never called, never exported.
4. **Shrink duplicated CRUD and writer patterns** into shared helpers.
5. **Unexport internal-only symbols** so dead-export linting works end-to-end.

## Task List

### Backend

- [ ] **B1**: Delete `backend/scripts/migrate_extract_connections.py`, `migrate_embedded_endpoints.py`, `migrate_field_refs.py`, `migrate_extract_lookups.py` (plan 015 one-shots; migration 037 wiped all old `pipelines` rows). Remove migration instructions from CLAUDE.md. [−648]
- [ ] **B2**: Delete `backend/scripts/load_test_direct_10m.py`; add `--file` arg to `load_test_direct.py`. [−106]
- [ ] **B3**: Delete `backend/dte/docker/entrypoint.py` (scaffolding for plan 036 distroless, Dockerfile still uses shell script). [−56]
- [ ] **B4**: Delete `EngineProtocol` from `backend/dte/engine/base.py`; re-export `BaseEngine` in `__init__.py`; delete the no-op test `TestEngineProtocol` in `tests/unit/test_engine_seam.py`. [−40]
- [ ] **B5**: Delete unused exception classes `SourceLoadError`, `DestinationWriteError`, `RunCancelled`, `RunTimeout` from `backend/dte/errors.py` (grep confirms zero raises/catches). [−16]
- [ ] **B6**: Delete back-compat aliases `*Create` from `backend/dte/models/pipeline.py`: `ConnectionCreate`, `SourceCreate`, `DestinationCreate`, `LookupTableCreate`, `PipelineCreate`, and `TenantCreate`. Verify the two migration scripts deleted in **B1** are the only callers. [−12]
- [ ] **B7**: Delete `backend/dte/models/pipeline.py` line 605 alias `DltSource = Source` and shim file `backend/dte/sources/dlt_loader.py` (tests already import `loader` directly). [−21]
- [ ] **B8**: Delete back-compat destination-type aliases `JsonFileTarget`, `CsvFileTarget`, `ExcelFileTarget`, `ParquetS3Target`, `JsonFileOutput` from `backend/dte/models/pipeline.py:963–974`. Sed one use in `engine/base.py:137`. [−6]
- [ ] **B9**: Delete legacy parameters from `backend/dte/sources/loader.py:486–556` — the 3-arg call support and `_fabricate_legacy_connection` helper. Update 24 test call sites in `test_documents_source.py` and `test_loader.py` to use the 5-arg form. [−60]
- [ ] **B10**: Delete unused settings fields `root_key`, `admin_enabled`, `allow_registration` from `backend/dte/config.py` (readers use `os.environ` directly, not Settings). [−10]
- [ ] **B11**: Delete no-op `get_settings.cache_clear` shim from `backend/dte/config.py:136–140` (only called once, in test conftest fixture that can be dropped). [−6]
- [ ] **B12**: Delete `backend/dte/sources/pools/engine.py` (DuckDB singleton pool, plan 028, never wired — `DTE_CONNECTION_POOL_ENABLED` is parsed but unused). Delete `tests/unit/test_pool_engine.py`. [−110]
- [ ] **B13**: Delete four unused exception classes and consolidate duplicate source-resolution logic in `backend/dte/api/routes/pipelines.py`: merge `_resolve_sources` into `_resolve`, dropping ~20 lines of loop duplication. [−20]
- [ ] **B14**: Extract shared `bulk-delete` helper from `backend/dte/api/routes/{connections,destinations,lookup_tables,sources,pipelines}.py`. One function `_bulk_delete(store, ids, referenced_by_fn)` in `backend/dte/api/routes/__init__.py` or a new `backend/dte/api/bulk_delete.py`; drop 5× `BULK_DELETE_LIMIT` + `BulkDeleteRequest` copies, standardise the drift. [−70]
- [ ] **B15**: Merge four writer modules (`csv_file.py`, `json_file.py`, `parquet.py`, `excel_file.py`) into `backend/dte/engine/writers/__init__.py` via a dispatch dict `{CsvTarget: ("FORMAT CSV, HEADER", None)}`. Keep `postgres.py` and `sql_database.py` as real modules (they have logic). Remove 4 isinstance branches. [−60]
- [ ] **B16**: Remove `python-multipart` from `backend/pyproject.toml` dependencies — no `Form`/`File`/`UploadFile` usage anywhere in `dte/`. Verify FastAdmin doesn't need it transitively before cutting. [−1 dep]

### Frontend

- [ ] **F1**: Delete unused UI exports `NavSearch`, `Kbd` from `frontend/src/components/ui/` (never rendered outside the UI kit); remove from `index.ts`. [−18]
- [ ] **F2**: Delete `StepRow` component `frontend/src/components/ui/step-row.tsx` (only shown in the `/preview` gallery, not in any product surface). [−25]
- [ ] **F3**: Delete 12 dead exports from `frontend/src/lib/api.ts` — `getCurrentUser`, `listPipelineRevisions`, `listLookupTables`, `getLookupTable`, `listConnectionSchemas`, `getSchedule`, `updateEvalSet`, `proposeEvalLabels`, `getLeaderboard`, `artifactKey`, `isArtifactRef`, `isJsonFileOutput`. [−80]
- [ ] **F4**: Unexport internal-only symbols from `frontend/src/components/builder/steps/editors.tsx` — the 9 per-step `*Editor` components (RenameEditor, RetypeEditor, etc.) are composed inside `StepEditor`, never imported elsewhere. [−0, API hygiene]
- [ ] **F5**: Unexport from `frontend/src/lib/api.ts` — `ContractType`, `EngineChoice`, `PipelineGateError`, `Page`, `apiFetchPage`, `TOKEN_STORAGE_KEY`, `TOKEN_COOKIE_NAME`. They're used only within the file. [−0, API hygiene]
- [ ] **F6**: Unexport from `frontend/src/components/builder/schedules/cron.ts` — `defaultScheduleFormState`, `expandField` are internals of the form; unexport + move defaulting to the component itself. [−0, API hygiene]
- [ ] **F7**: Backend endpoint: add `GET /api/schedules/preview?cron=<expr>&tz=<zone>` returning `{description: string, next_fires: [ISO, ISO, ISO]}`. Replace `frontend/src/components/builder/schedules/cron.ts` logic (`readCron`, `nextFireTimes`, ~250 lines) with one call. [−220 frontend, backend +30]

### Configuration

- [ ] **C1**: Add `.DS_Store` to the repo-root `.gitignore` — currently untracked and unignored. [−0]
- [ ] **C2**: Add `.codegraph/`, `.cursor/`, `.gemini/`, `.mcp.json` to the repo-root `.gitignore` — local tool dirs, currently untracked and unignored (commit `.env.example` only, never the real `.env`). [−0]

### Testing

- [ ] **T1**: Update `backend/tests/unit/test_documents_source.py` (7 call sites) and `backend/tests/unit/test_loader.py` (17 call sites) to use new `load_source(source, registry, connection, credentials, table=None)` signature instead of legacy 3-arg form. [No new tests needed — these are fixture updates.]

## Files Changed / Deleted

### Deleted

```
backend/scripts/migrate_extract_connections.py
backend/scripts/migrate_extract_lookups.py
backend/scripts/migrate_embedded_endpoints.py
backend/scripts/migrate_field_refs.py
backend/scripts/load_test_direct_10m.py
backend/dte/docker/entrypoint.py
backend/dte/sources/dlt_loader.py
backend/dte/sources/pools/engine.py
backend/tests/unit/test_pool_engine.py
frontend/src/components/ui/step-row.tsx
frontend/src/components/ui/sidebar.tsx (NavSearch component, keep the rest)
```

### Modified

```
backend/dte/engine/base.py                          (delete EngineProtocol)
backend/dte/engine/__init__.py                       (re-export BaseEngine)
backend/dte/errors.py                               (delete 4 exception classes)
backend/dte/models/pipeline.py                      (delete 6 aliases, 1 legacy line)
backend/dte/config.py                               (delete 3 fields, 1 shim)
backend/dte/sources/loader.py                       (delete legacy shim, 60 lines)
backend/dte/engine/writers/__init__.py              (merge 4 file-writer delegates)
backend/dte/engine/writers/{csv_file,json_file,parquet,excel_file}.py (delete or merge)
backend/dte/api/routes/pipelines.py                 (merge _resolve_sources into _resolve)
backend/dte/api/routes/{connections,destinations,lookup_tables,sources,pipelines}.py  (extract bulk-delete helper)
backend/dte/api/routes/schedules.py                 (add /preview endpoint)
backend/CLAUDE.md                                   (remove migration script instructions)
backend/pyproject.toml                               (remove python-multipart dependency)
backend/tests/unit/test_compiler_errors.py          (s/JsonFileTarget/JsonTarget/)
backend/tests/unit/test_pipeline_spec.py            (s/JsonFileTarget/JsonTarget/ etc., 6 aliases)
backend/tests/unit/test_writers_local.py            (s/JsonFileTarget/JsonTarget/ etc.)
backend/tests/unit/test_documents_source.py         (update load_source calls, 7 sites)
backend/tests/unit/test_loader.py                   (update load_source calls, 17 sites)
backend/tests/unit/test_engine_seam.py              (delete TestEngineProtocol)
backend/tests/unit/test_deps.py                     (delete cache_clear call)
frontend/src/components/ui/index.ts                 (remove NavSearch, Kbd, StepRow exports)
frontend/src/lib/api.ts                             (delete 12 exports, unexport 6 symbols)
frontend/src/components/builder/steps/editors.tsx   (unexport 9 *Editor components)
frontend/src/components/builder/schedules/cron.ts   (replace readCron/nextFireTimes with API call, unexport internals)
.gitignore                                          (repo root: add .DS_Store, .codegraph, .cursor, .gemini, .mcp.json)
```

## Constraints & Notes

- **Alembic migrations** are write-only history; don't touch them.
- **Backend bulk-delete duplication** has started drifting (pipelines version cascades child runs; others don't). The consolidation enforces consistency.
- **Writers**: `json`, `csv`, `excel`, `parquet` all just delegate to `copy_to`; the refactor is pure dispatch. `postgres` and `sql_database` stay as separate modules — they have real logic.
- **Cron frontend↔backend split**: DST edge cases appear twice today (zoneinfo in both). The backend has it right (croniter + zoneinfo). Moving to a preview endpoint keeps frontend code simple and the source of truth in one place.
- **Test fixtures**: No new test coverage needed — we're deleting, not adding.

## Rollout

No feature gates or phases. The deletions are mechanical and independently verifiable:

1. Delete orphaned files (scripts, docker, dlt_loader shim).
2. Delete/consolidate back-compat shims (settings, aliases, exception classes).
3. Refactor duplicated patterns (bulk-delete, writers, _resolve).
4. Shrink frontend API surface (unexport, delete dead helpers).
5. Add `/schedules/preview` endpoint; migrate frontend cron logic.
6. Run full test suite; merge.

Timeline: 2–3 hours of focused work.
