# Plan 015 — First-class sources and destinations

## Context

Today both ends of a pipeline are embedded on it: `Pipeline.sources: list[Source]` and `Pipeline.output: OutputTarget`. Consequences:

- Duplicate credentials — same S3 bucket / Postgres instance configured on multiple pipelines means multiple copies of the same key pair.
- No central inventory. Users have no page to answer "what sources / destinations do we know about?"
- No reuse. A working config lives inside one pipeline and gets copy-pasted (or lost).

Make **sources** and **destinations** first-class: each gets its own table, CRUD, and page. Pipelines reference both by id; the builder either picks an existing one or spawns a new one inline (that inline creation persists to the table).

## Non-goals

- Sharing model / permissions. Everything visible to everyone; single-tenant stays.
- Versioning source or destination configs. Latest wins; runs use whatever the current config is at run time.
- Any change to how sources actually load or how outputs write — `load_source()` still consumes a `Source`, writers still consume an output config; we just resolve ids first.
- Multiple outputs per pipeline. Stays 1:1 for now (`Pipeline.output_id: str`). If we want fan-out later it becomes `list[str]` in a follow-up.

## Architecture

### Backend model

- **Rename** `DltSource` → `Source` in `backend/dte/models/pipeline.py`. The name was a leftover from when every source_type went through dlt; today only `mongodb` and `rest_api` do. `filesystem`, `s3`, `gcs`, `azure`, `sql_database` route through native DuckDB. Keep `DltSource` as a deprecated alias for one release to avoid breaking imports; delete after Task 7.
- Rename `dte/sources/dlt_loader.py` module → `dte/sources/loader.py` in the same commit; update every import.
- **New `Destination` model** in `backend/dte/models/pipeline.py`: `id: str`, `type: Literal[...]` (same discriminator as today's `OutputTarget`), plus the type-specific fields (`path`, `credentials`, etc.). Extract from the current `JsonFileTarget` / `CsvFileTarget` / `ParquetS3Target` / `PostgresTarget` / `SqlDatabaseTarget` union — payload shape unchanged, only the wrapper gains an `id`.
- `Source.id` becomes globally unique — PK of a new `sources` table.
- `Destination.id` — PK of a new `destinations` table.
- `Pipeline.sources: list[str]` — ordered list of source ids. First entry is the compiler's `current_key` seed.
- `Pipeline.output_id: str` — id of the destination this pipeline writes to.
- New protocols `SourceStore` and `DestinationStore` mirroring `PipelineStore` (`backend/dte/store/base.py:5`): `get`, `save`, `list`, `delete`.
- `MemorySourceStore`, `MemoryDestinationStore` (mirror `MemoryPipelineStore` in `backend/dte/store/memory.py`).
- `PostgresSourceStore`, `PostgresDestinationStore` + tables (mirror `PostgresPipelineStore` in `backend/dte/store/postgres.py`).
- Alembic `004_sources_and_destinations.py` — `sources` and `destinations` tables. Same column shape: `id text PK`, `type text`, `config jsonb`, `created_at`, `updated_at`. (Sources also carry `table text`.)

### API

**Sources**
- `POST   /api/sources` — create. 409 on id collision.
- `GET    /api/sources` — list.
- `GET    /api/sources/{id}` — read.
- `PUT    /api/sources/{id}` — update. Id not renamed.
- `DELETE /api/sources/{id}` — 409 with `{"referenced_by": [pipeline_ids]}` if any pipeline still references it. No force flag. Users must detach via the builder first.
- `POST   /api/schema/infer` — unchanged (in-flight `Source` payload; used before a source is saved).
- `GET    /api/sources/{id}/schema` — NEW. Looks the source up and runs the same inference; client sends only the id.

**Destinations**
- `POST   /api/destinations` — create. 409 on id collision.
- `GET    /api/destinations` — list.
- `GET    /api/destinations/{id}` — read.
- `PUT    /api/destinations/{id}` — update.
- `DELETE /api/destinations/{id}` — 409 with `{"referenced_by": [pipeline_ids]}` if any pipeline references it via `output_id`. Detach first.

**Pipeline execution**
- `POST /api/pipelines/{id}/trigger` and `/preview` — resolve each id in `pipeline.sources` via `SourceStore.get`, resolve `pipeline.output_id` via `DestinationStore.get`, then hand the compiler + executor the resolved objects. Missing id → 422 naming what's missing.
- Pipeline create/update: validate that every source id and the destination id exist. 422 if not.

### Frontend

- New route `/sources` — list + create + edit + delete. Same layout language as `/pipelines`.
- New route `/destinations` — parallel to `/sources`. The existing `OutputPanel` becomes the editor.
- Pipeline builder replaces the embedded-editor SourcesPanel + OutputPanel with picker components:
  - **Sources**: dropdown per slot (`id · source_type · bucket_url|host preview`), plus "**+ New source…**" that opens `SourceEditor` inline. On save → `POST /api/sources` and append the id. "**Edit**" pre-loads the inline editor and saves via `PUT` (hint copy: "shared with other pipelines").
  - **Destination**: single dropdown of saved destinations, plus "**+ New destination…**" inline creator using the existing output editor. "**Edit**" flows the same way as sources.
  - Sources keep reorder + remove; the destination slot is single-value with a change action.
- `BuilderForm` (`frontend/src/components/builder/BuilderForm.tsx`) validation: `sources.length ≥ 1`, `output_id` set, every id resolves in the sources / destinations SWR lists.
- `SchemaProvider` (`frontend/src/components/builder/schema-context.tsx`): for saved sources calls `GET /api/sources/{id}/schema`; for in-flight (unsaved) sources continues to `POST /api/schema/infer` with the body.

### Migration

`backend/scripts/migrate_embedded_endpoints.py` (one script, both directions):
- For every pipeline:
  - Upsert each embedded `Source` into the sources table with its current id. Collision on id-with-different-config: append `-2`, `-3`, … and log.
  - Upsert the embedded `output` into the destinations table. Since embedded outputs have no id today, generate one: `<pipeline_id>_output` (falling back to `-2`, … on collision).
- Replace `pipeline.sources` with the list of ids and `pipeline.output` with `pipeline.output_id`.
- Idempotent — running twice is a no-op.

## Reused code

- `resolve_secret()` (moving from `backend/dte/sources/dlt_loader.py:12` → `backend/dte/sources/loader.py`) — unchanged; sources still route credentials through it at load time.
- `SourceEditor.tsx` (`frontend/src/components/builder/sources/SourceEditor.tsx`) — reused as-is inside the new `/sources` create/edit pages and the inline "+ New source" flow.
- `OutputPanel.tsx` (`frontend/src/components/builder/OutputPanel.tsx`) — reused as-is inside the new `/destinations` pages and the inline "+ New destination" flow.
- `SOURCE_KINDS` + `emptySource()` (`frontend/src/components/builder/sources/types.ts`) — reused verbatim.
- The existing `OutputTarget` discriminated union (`backend/dte/models/pipeline.py`) — wrapped inside `Destination` unchanged.
- `PostgresPipelineStore` pattern (`backend/dte/store/postgres.py`) — copy the same `async_sessionmaker` + `MetaData` shape for both new stores.

## Tasks (each = one worktree, one branch, one PR)

### Task 1 — Backend: rename `DltSource` → `Source`; `SourceStore` + `DestinationStore`; `Pipeline` refs
- Branch: `feature/backend-source-dest-stores`
- Files:
  - `backend/dte/models/pipeline.py` — rename `DltSource` → `Source`; new `Destination` model wrapping the existing discriminated `OutputTarget`; change `Pipeline.sources` to `list[str]`; change `Pipeline.output: OutputTarget` to `Pipeline.output_id: str`; keep `DltSource = Source` alias.
  - `backend/dte/sources/dlt_loader.py` → **rename** to `backend/dte/sources/loader.py`; update imports (`backend/dte/api/routes/schema.py:5`, `backend/dte/api/routes/pipelines.py:8`, all tests). Keep a shim `dlt_loader.py` re-exporting for one release.
  - `backend/dte/store/{base,memory,postgres}.py` — add `SourceStore`, `DestinationStore`, memory + Postgres implementations.
  - `backend/alembic/versions/004_sources_and_destinations.py` (new) — creates both tables.
  - `backend/dte/api/deps.py` — `get_source_store()`, `get_destination_store()`.
  - `backend/tests/unit/test_source_store.py`, `test_destination_store.py` (new).
  - Rename `backend/tests/unit/test_dlt_loader.py` → `test_loader.py`.

### Task 2 — Backend: `/api/sources` + `/api/destinations` routes + pipeline execution rewire
- Branch: `feature/backend-sources-dests-api`
- Files:
  - `backend/dte/api/routes/sources.py` (new) — 5 CRUD endpoints **plus** `GET /api/sources/{id}/schema`.
  - `backend/dte/api/routes/destinations.py` (new) — 5 CRUD endpoints.
  - `backend/dte/api/routes/pipelines.py` — resolve source ids + destination id before compiling; validate on save; DELETE returns 409 when referenced (via `SourceStore` / `DestinationStore` back-references).
  - `backend/dte/api/main.py` — register both routers.
  - `backend/tests/unit/test_api_sources.py`, `test_api_destinations.py` (new); update `test_api_pipelines.py`; add a case in `test_api_schema.py` for the by-id endpoint.

### Task 3 — Backend: migration script for embedded sources + outputs
- Branch: `feature/backend-migrate-embedded-endpoints`
- Files:
  - `backend/scripts/migrate_embedded_endpoints.py` (new)
  - `backend/tests/unit/test_migrate_embedded_endpoints.py` (new)

### Task 4 — Frontend: `/sources` page
- Branch: `feature/frontend-sources-page`
- Files:
  - `frontend/src/app/(app)/sources/{page,new,[id]/edit}.tsx` (new)
  - `frontend/src/lib/api.ts` (`listSources`, `getSource`, `createSource`, `updateSource`, `deleteSource`)
  - `frontend/src/lib/api-types.ts` (regen after Task 2)
  - `frontend/src/components/app-sidebar.tsx` (nav entry above Pipelines)

### Task 5 — Frontend: `/destinations` page
- Branch: `feature/frontend-destinations-page`
- Files:
  - `frontend/src/app/(app)/destinations/{page,new,[id]/edit}.tsx` (new)
  - `frontend/src/lib/api.ts` (`listDestinations`, `getDestination`, `createDestination`, `updateDestination`, `deleteDestination`)
  - `frontend/src/components/builder/OutputPanel.tsx` — split into a pure editor component that both `/destinations/new` and the inline creator can reuse.
  - Sidebar entry.

### Task 6 — Frontend: builder uses source + destination refs
- Branch: `feature/frontend-builder-refs`
- Files:
  - `frontend/src/components/builder/sources/SourcesPanel.tsx` — rewrite as picker + inline creator.
  - `frontend/src/components/builder/BuilderForm.tsx` — validation: `sources.length ≥ 1`, `output_id` set, all ids resolve.
  - `frontend/src/components/builder/schema-context.tsx` — saved sources call `GET /api/sources/{id}/schema`; in-flight sources keep `POST /schema/infer`.
  - New `frontend/src/components/builder/DestinationPicker.tsx` — parallel of SourcesPanel for the single output.

### Task 7 — Docs
- Branch: `feature/docs-first-class-endpoints`
- Files: `CLAUDE.md` — new subsection covering both stores + refs; update the Builder subsection.

## Verification

1. `cd backend && uv run pytest -x` — all green (existing + new store/route/migration tests).
2. Fresh Postgres: `alembic upgrade head` creates `sources` and `destinations` tables.
3. Docker stack up.
4. `POST /api/sources` with an S3 body → 201 with id.
5. `POST /api/destinations` with a `json_file` body → 201 with id.
6. `POST /api/pipelines` referencing both ids → 201.
7. `POST /api/pipelines/{id}/trigger` → runs; loader receives the resolved `Source`, writer receives the resolved `Destination`.
8. `DELETE /api/sources/{id}` (or `/api/destinations/{id}`) while a pipeline references it → 409 with `referenced_by`. Edit the pipeline to remove the id, retry → 200.
9. `GET /api/sources/{id}/schema` → returns the same nested tree as `POST /schema/infer`.
10. Pre-load a fixture pipeline with an embedded source + output, run `python scripts/migrate_embedded_endpoints.py --write`, verify both rows land in their tables and the pipeline references them by id.
11. In the UI: `/sources` and `/destinations` list; the builder's pickers show them; "+ New …" inline creates + attaches; editing an existing entry in the builder updates the shared record and reflects on the listing pages. Attempting to delete a still-referenced entry shows the referencing pipelines in the error.

## Breaking changes

- Clients POSTing to `/api/pipelines` with `sources: [{…embedded…}]` or `output: {…embedded…}` get 422 after Task 2. Migrate first (Task 3), then deploy.
- In dev (memory store) a restart is enough — no state to migrate.
- Any external caller of `POST /api/schema/infer` continues to work unchanged; the new `GET /api/sources/{id}/schema` is additive.
