# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo layout

```
backend/       Python package `dte`, alembic, tests, Dockerfile
frontend/      Next.js app
docker-compose.yml   whole stack (postgres + backend + frontend)
plans/         feature plans (numbered)
```

All Python paths in this file are relative to `backend/`.

## Commands

### Docker (recommended for anything cross-service)

```bash
# Bring up the stack (postgres + backend + frontend, dev-mode hot reload)
docker compose up -d --build

# Follow logs
docker compose logs -f backend

# Restart a single service after a config change
docker compose restart backend

# Tear down (keeps pgdata volume)
docker compose down
```

Dev mode is wired: `./backend/dte` and `./backend/alembic` mount into the backend container; uvicorn runs with `--reload`. Frontend mounts `./frontend` and runs `pnpm dev`. Ports are `3000` (frontend), `8001` (backend), `5432` (postgres).

### Backend without Docker

Run from inside `backend/`:

```bash
cd backend

# Install
uv venv && uv pip install -e ".[dev]"

# Run all tests
uv run pytest

# Single test
uv run pytest tests/unit/test_compiler.py::test_join_inner

# Coverage
uv run pytest --cov=dte

# Skip postgres integration tests (requires DATABASE_URL)
uv run pytest -m "not integration"

# Start API server
uv run uvicorn dte.api.main:app --port 8001 --reload

# DB migrations (requires DATABASE_URL, sync driver e.g. postgresql://)
uv run alembic upgrade head
```

### Frontend

```bash
cd frontend && pnpm install && pnpm dev   # http://localhost:3000
cd frontend && pnpm gen:types             # regen types (backend must be up)
```

## Frontend

Next.js **16** (App Router, Turbopack) + Tailwind **v4** + React **19** + TypeScript. Package manager is **pnpm**. Read this section before opening frontend files — most non-obvious choices are captured here.

### Ports and env

- Frontend dev on **`:3000`**.
- Backend on **`:8001`** (an unrelated Django dev server squats on `:8000` in this dev environment). Start with `uvicorn dte.api.main:app --port 8001 --reload` from repo root.
- `frontend/.env.local` sets `NEXT_PUBLIC_API_URL=http://localhost:8001`. `.env.local.example` is committed (`.gitignore` has `!.env.local.example`); actual `.env.local` isn't.
- Backend CORS reads `DTE_CORS_ORIGINS` (default `http://localhost:3000`).
- `NEXT_PUBLIC_*` values are inlined at build time — **restart `pnpm dev` after changing them**.
- `Run` model has `started_at`/`finished_at` (iso strings). Frontend derives elapsed client-side.

### Route structure (App Router)

```
src/app/
  layout.tsx           # html + fonts + ThemeProvider + SwrProvider (client tree wrapper)
  page.tsx             # redirect /  →  /pipelines
  (app)/               # route group sharing the sidebar shell
    layout.tsx         # grid: <AppSidebar/> + <main>
    pipelines/{page, new, [id]/{page, edit}}.tsx
    runs/[id]/page.tsx
    preview/page.tsx   # component gallery ("/preview")
```

- `/runs` (no id) intentionally has **no page** — reach a run via its pipeline detail. The sidebar link was removed.
- `AppSidebar` is a client component (`usePathname` for active state); everything above it in the tree stays server-render-eligible.

### Design system (portable)

- `src/components/ui/` imports only from itself + `@/lib/cn.ts`. To port to another project: copy this folder + `src/app/globals.css` + the three Google fonts wired in `layout.tsx`. Anything in `src/components/builder/` is DTE-specific.
- Tokens live in `globals.css` as CSS vars under `[data-theme="dark"]` and `[data-theme="light"]`, remapped into Tailwind's `@theme` (so `bg-surface`, `text-muted`, `border-border`, etc. work).
- Theme is switched by setting `data-theme` on `<html>` via `ThemeProvider` (`useTheme()` hook; state persisted to localStorage).
- Fonts: **Outfit** (all UI), **Space Mono** (paths / code / mono metadata), **Cormorant Garamond** — reserved for the `dt·e` wordmark only. Do not use Cormorant for headings or numerals; earlier attempts read as landing-page marketing, not product.
- Every color the app uses (including status pills, run tones, code bg) comes from tokens. Don't hardcode hex values in components.

### Design vocabulary (`components/ui/`)

`Button` (variants: default/primary/ghost × sm/md, optional `kbd`), `Pill` (`ok`/`running`/`failed`/`pending`), `Panel` + `PanelHead`, `PageHeader`, `SectionHead`, `Sidebar` (+ `Brand`, `NavSearch`, `NavItem`, `NavGroup`, `NavFooter`), `Topbar`, `DataTable<T>` (client), `StepRow`, `ExprCode`/`ExprToken`, `KV`/`KVItem`, `AddStep`, `Item`, `Tag`, `Metric` + `MetricRow`, `Timeline` + `TimelineRow` + `InlineCode`, `Field`/`Input`/`Textarea`/`Segmented`, `FieldPicker`, `FieldMultiSelect`, `ThemeToggle`. Re-exports through `components/ui/index.ts`.

### API client + typegen

- `src/lib/api-types.ts` is generated from the running backend's `/openapi.json`. Regen: **backend must be up on `:8001`**, then `pnpm gen:types` (script sets `DTE_API_URL=http://localhost:8001` if you export it, otherwise defaults to `:8000`). Fastest form: `DTE_API_URL=http://localhost:8001 ./scripts/gen-api-types.sh`.
- `src/lib/api.ts` is the hand-written wrapper: `apiFetch<T>`, named helpers (`listPipelines`, `getPipeline`, `createPipeline`, `updatePipeline`, `deletePipeline`, `triggerPipeline`, `previewPipeline`, `listPipelineRuns`, `getRun`, `inferSchema`), `Run` type (backend returns dict; typed here), `isTerminal`, `isJsonFileOutput` narrower.
- SWR wired in `src/lib/swr-config.tsx` with `fetcher: (path) => apiFetch(path)`. `refreshInterval` on the run page uses `(latest) => isTerminal(latest?.status) ? 0 : 2000`.

### Next 16 gotchas (breaking from earlier versions)

- `params` and `searchParams` are `Promise`s. In server components: `const { id } = await params`. In client components: `const { id } = use(params)`.
- Type helpers `PageProps<'/route'>` and `LayoutProps<'/route'>` are globally available — no import — generated during `next dev`/`build`/`typegen`.
- `frontend/AGENTS.md` warns: "This is NOT the Next.js you know." When uncertain, read `frontend/node_modules/next/dist/docs/01-app/` before writing code.

### Server vs client component discipline

**The single most common bug in this codebase**: passing a function (event handler or a `render` fn in a `columns` array) from a server component into a client component. FastAPI-fed pages are server components by default. `DataTable` is `"use client"`. Any prop with a function payload — `onRowClick`, `columns[].render` — must originate inside a client component.

Pattern used throughout: extract client sub-components (`PipelinesTable`, `RunsTable`, `TriggerButton`, `PipelinePreview`) that own the handlers; server pages compose them.

Ref forwarding: React 19 lets `ref` ride as a normal prop. `Input` does this so `FieldPicker` can focus/blur it — do the same for any new form primitive.

### FieldPicker portal (do not remove)

`FieldPicker` renders its popover via `createPortal(..., document.body)` with `position: fixed`. This is deliberate — `Panel` uses `overflow-hidden` for its rounded corners, which would otherwise clip the dropdown. Position is recomputed on `scroll` (capture) and `resize`. `FieldMultiSelect` composes `FieldPicker`.

Field autocomplete data comes from `SchemaProvider` (`components/builder/schema-context.tsx`) — a React context storing `{ [source_id]: {fields, loading, error} }` derived from `POST /api/schema/infer`, plus a `allFields` deduped union. The user drives inference with the **Infer schema** button on each `SourceEditor`.

### Builder

- `BuilderForm` wraps everything in `<SchemaProvider>` and validates on submit: id required + alphanumeric/`_`/`-`, name required, at least one source picked, destination picked, no empty-`fields` select step. Pipelines carry id refs (`sources: string[]`, `output_id: string`); the picker components (`SourcesPanel`, `DestinationPicker`) resolve those against the `/api/sources` and `/api/destinations` SWR lists.
- `SourcesPanel` is a per-slot dropdown with reorder + remove + "+ New source" inline creator. Inline save POSTs to `/api/sources` and appends the id. "Edit" pre-loads a saved source and PUTs — hint copy notes it's shared across pipelines.
- `DestinationPicker` is the single-value parallel for the output slot.
- `SchemaProvider` exposes `refresh(source)` for in-flight (unsaved) sources — which POST `/api/schema/infer` with the body — and `refreshById(id)` for saved sources, which GETs `/api/sources/{id}/schema`. `AutoInferSchemas` on the builder uses the id path.
- `StepsPanel` owns the ordered list, reorder (↑/↓ buttons), remove, and an "Add step" menu keyed off `STEP_OPS`.
- Every op has a dedicated editor in `components/builder/steps/editors.tsx` — one file so the dispatch is easy to read. Each editor emits the exact dict shape the backend expects.
- `Rename`, `MapLookup.table`, and `Select` maintain local UI state that syncs to the parent's parsed form via a `useEffect` guarded by shallow equality — needed so mid-typing (`"customer_id →"` with no RHS yet) isn't wiped by the parser.
- `Filter` has **Basic** / **Advanced** tabs. Basic composes DuckDB SQL with `quoteIdent`/`safeLiteral` — identifiers wrapped in `""` (internal `"` → `""`); values dispatched: bare ints/floats pass through, `true`/`false` pass through as booleans, everything else becomes a `''`-quoted string with internal `'` → `''`. Zero SQL injection surface in Basic. Advanced is raw SQL and the hint says so.
- `Select` step (op `select`) is the projection editor. Two modes on `Segmented`: **Keep** (chip picker + optional aliases) and **Drop** (chip picker of what to strip). Drop mode is fully derived: a `useEffect` on `(mode, dropped, allFields)` sets `fields = allFields − dropped`, so switching to Drop mode with a schema immediately populates the keep set. If schema is missing, an inline "infer schema first" placeholder shows instead.
- **Nested fields.** `filesystem` sources return STRUCT columns (DuckDB native). `/api/schema/infer` returns a nested tree; `FieldTreePicker` renders it. **Wire form is dot syntax** (`order.amount`) — matches the struct member path, matches ibis, matches SQL. `field-tree.ts` accepts either the backend's `children[]` tree directly or a flat list of dot-form leaves and builds a trie. `_dlt_*` (still produced by `mongodb` / `rest_api` via dlt) stay as flat top-level leaves. Legacy `parent__child` refs are auto-normalised by `toWire()` on read and can be migrated persistently with `backend/scripts/migrate_field_refs.py`.

### Output — discriminated union

Backend `output` is now a Pydantic discriminated union over `type`: `json_file` | `csv_file` | `excel_file` | `parquet_s3` | `postgres` | `sql_database`. The UI **only edits `json_file`** today. `isJsonFileOutput(pipeline.output)` narrows before reading `.path`. `BuilderForm` shows a placeholder card for other types. When adding an output editor, follow the same pattern: narrow with the type guard, don't add optional chaining to bypass the union.

### Sources

`components/builder/sources/` — the multi-type source editor. Per-kind config editors: `filesystem` (bucket_url/directory + file_glob), `sql_database` (connection_string + table/query), `mongodb` (connection_url + database + collection). Adding a new kind means: add to `SOURCE_KINDS`, add a `CONFIG_TEMPLATES[kind]`, write a `<Kind>SourceEditor.tsx`, dispatch in `SourceEditor.tsx`. `filesystem`'s `bucket_url` must be a **directory** — the label + hint explicitly say so; users hit this repeatedly if the hint is softened.

### Run detail

Client-only page (`use(params)` + `useSWR`). Polls `/api/runs/{id}` every 2s until `isTerminal(status)`. Shows `MetricRow` (rows written, elapsed = client-computed from timestamps, started_at localised, engine=DuckDB) + error `<pre>` on failure. The `Timeline` component is stubbed with an "events not recorded yet" state — kept in the kit so we don't rewrite it when per-step events land backend-side.

### Preview / dry run

`PipelinePreview` (client) hits `GET /api/pipelines/{id}/preview?limit=20` and renders sample rows in a themed table. Wired on the pipeline detail page above Recent runs. Errors (compile-time, e.g. `retype` on `"0.1.0"` → float) surface in a red panel — this is the fastest debugging path.

### When adding a new step op

1. Backend: add `Xxx` Pydantic model in `dte/models/pipeline.py`, dispatch in `dte/compiler/ibis_compiler.py`, add compiler tests first.
2. `pnpm gen:types` (backend up on `:8001`) — this refreshes `frontend/src/lib/api-types.ts`.
3. Frontend: extend `StepOp` + `STEP_OPS` + `emptyStep()` in `components/builder/steps/types.ts`.
4. Write `XxxEditor` in `editors.tsx`; dispatch from `StepEditor` at the bottom. Use `useSchemas().allFields` for any field references.


## Architecture

DTE is a batch data transformation engine. A **Pipeline** (Pydantic model) describes sources, ordered transform steps, and an output target.

### Full data flow

```
DltSource config(s)
    ↓
dlt_loader.load_source() → ibis.Table per source (loaded into shared DuckDB connection)
    ↓
compile_pipeline(pipeline, tables) → ibis.Table (transformed)
    ↓
DuckDBEngine.execute_to_json() → output file + row count
```

### Key modules

**`dte/models/pipeline.py`** — the pipeline spec. `Pipeline.steps` is `list[dict]` (not a typed Union) because the `map` op requires a sub-discriminator on `mode` that Pydantic's discriminated union can't handle with a shared `op` key. The compiler parses each step dict by `op`/`mode`.

**`dte/sources/dlt_loader.py`** — universal source loading. `load_source(DltSource, ibis_con)` returns an `ibis.Table` bound to the shared DuckDB connection. The dispatch splits by source_type:

- **`filesystem`**: `read_json_auto` / `read_csv_auto` / `read_parquet` / `read_xlsx` via `CREATE OR REPLACE VIEW`. No dlt. Nested JSON comes through as STRUCT columns; format is detected by extension (`.json`, `.jsonl`, `.ndjson`, `.csv`, `.tsv`, `.parquet`, `.xlsx`) and `config["format"]` overrides. `.xlsx` uses DuckDB's `excel` extension (lazy `INSTALL excel; LOAD excel;`) and reads only the first sheet.
- **`sql_database`**: DuckDB scanner extensions (`INSTALL sqlite|postgres|mysql; ATTACH … (TYPE …, READ_ONLY); CREATE VIEW`). Scheme detected from the SQLAlchemy-style `credentials` URL. No dlt.
- **`s3`, `gcs`, `azure`**: DuckDB native remote reads. `s3` and `gcs` go through the `httpfs` extension; `azure` through the `azure` extension. Each loader installs the extension, emits `CREATE OR REPLACE SECRET <scoped-name> (TYPE …, …)`, then materialises `bucket_url + file_glob` via `read_json_auto` / `read_csv_auto` / `read_parquet` in a `CREATE OR REPLACE VIEW`. **GCS auth is HMAC-only** — supply `hmac_key_id` + `hmac_secret`; the old `credentials_json` (service-account JSON) is rejected. **Azure auth**: `connection_string` (preferred) or `account_name` + `account_key`.
- **`mongodb`, `rest_api`**: dlt (`@dlt.resource` + `dlt.sources.rest_api.rest_api_source`). Kept because dlt's pagination / normalisation earn their keep for real APIs. Their columns still come through with `__` flattening — refs to them are single-token identifiers, not path expressions.

**`dte/compiler/ibis_compiler.py`** — `compile_pipeline(pipeline, tables)` maintains a **named registry** (`dict[str, ibis.Table]`) instead of a rolling variable. Each step reads from and writes back to the registry via `current_key`. Join steps write their result under `output_id` and update `current_key`. This allows multi-source pipelines.

- Filter and expression-map steps escape to raw SQL via `con.create_view()` + `con.sql()` — Ibis has no SQL string parser. This is the seam for future distributed backends (Spark, Trino).
- Pivot uses `con.con.execute("CREATE OR REPLACE TEMP TABLE ... AS PIVOT ...")` — dynamic PIVOT cannot be a view in DuckDB, and `con.sql()` fails because sqlglot can't subquery a PIVOT node.

**`dte/engine/duckdb_engine.py`** — wraps `ibis.duckdb.connect()`. Exposes `con` property (the ibis backend) for use by `dlt_loader`. Only responsible for execution and output — does not load sources.

**`dte/store/`** — Protocols in `base.py`, one per persisted entity: `PipelineStore`, `SourceStore`, `DestinationStore`, `ConnectionStore`, `RunStore`. `postgres.py` is the sole production backend (SQLAlchemy async, requires `DATABASE_URL`). Tests use `tests/fakes.py` — there is no in-memory store shipped in the package. The active backend is wired in `dte/api/deps.py` and injected into routes via FastAPI `Depends()`. All four Pydantic-modelled stores speak typed SQLModel instances end-to-end (see the **Model + store pattern** subsection below); `PostgresRunStore` still hand-writes SQL because `Run` isn't a Pydantic model yet.

**`dte/api/`** — FastAPI app. Routes use `Depends(get_pipeline_store)` and `Depends(get_run_store)`. Tests override these with `app.dependency_overrides`. `_execute_pipeline` runs as an `asyncio.create_task` — trigger returns `run_id` immediately, caller polls `GET /api/runs/{run_id}`.

### Step dispatch

```python
op = step["op"]    # "filter"|"rename"|"retype"|"map"|"sort"|"aggregate"|"join"|"pivot"|"select"
mode = step.get("mode")   # "lookup"|"expression"|"calculation"  — map steps only
```

### Field references and nested columns

Dot syntax is the wire form: `order.amount`, `user.address.city`. `_resolve_field()` splits on `.` and traverses struct members; if the head isn't a top-level column it falls back to the joined `__` name (so `mongodb` / `rest_api` sources — which still flatten via dlt — keep working). `_apply_output_fields` / `_apply_lookup` route through `_resolve_field` so Select and Lookup steps handle struct paths. Struct-path outputs are named after the leaf segment when no alias is given.

To migrate saved pipelines from `parent__child` to `parent.child`:
```bash
cd backend && uv run python scripts/migrate_field_refs.py           # dry run
cd backend && uv run python scripts/migrate_field_refs.py --write   # persist
```

### Ibis version notes

- ibis ≥ 9: use `ibis.cases(*[(condition, value), ...], else_=default)`, **not** `ibis.case()`
- `table.rename({new_name: old_name})` — ibis rename direction is reversed from intuition

## Connections (three-tier model)

Sources and destinations reference a **Connection** by `connection_id`. A Connection holds only credentials (opaque encrypted blob). Sources / destinations hold only the "where inside the target" bits (bucket_url, schema+table, collection, path). Local file targets bind to a no-cred `local_fs` connection so every source and destination has exactly one connection to point at.

Three tiers:

```
Connection (credentials)
    ↑
Source / Destination (references connection_id + carries kind-specific config)
    ↑
Pipeline (references source ids + destination id)
```

### Credential validation via dlt's `@configspec` classes

`Connection.credentials` is validated at model-parse time by instantiating the matching dlt spec class (`dlt.common.configuration.specs.AwsCredentials`, `ConnectionStringCredentials`, etc). We do NOT inherit — that would drag in dlt's config-provider machinery. Instead we call the class, extract public fields via `dataclasses.fields()`, drop dlt's built-in defaults and Nones, and store the result as an opaque dict. See `_DLT_CRED_CLASS` in `dte/models/pipeline.py`.

**Rule for adding a new integration**: add the connection type to `ConnectionType`, add the dlt cred class to `_DLT_CRED_CLASS`, and (for SQL-family) route through `ConnectionStringCredentials` — dlt destinations accept the resulting URL directly.

`ConnectionString`-family (postgres/mysql/sqlite/snowflake/bigquery/mongodb) collapses to `{"url": "..."}` on store — same shape dlt destinations accept.

### Secret resolver seam

`dte/secrets/` — pluggable resolver interface. Two shipped:
- **EnvSecretResolver** (default in dev): stores plaintext JSON; resolves `{env: "X"}` values from `os.environ` at decrypt time. Preserves the plan-014 env-indirection UX.
- **FernetSecretResolver** (prod): symmetric encryption via `cryptography.fernet.Fernet`. Key from `DTE_SECRETS_KEY` env var (generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).

`get_secret_resolver()` in `dte/secrets/__init__.py` picks:
1. `DTE_SECRETS_BACKEND=env|fernet` — explicit override.
2. `DTE_SECRETS_KEY` set → Fernet.
3. else → Env resolver, with a startup warning if `DATABASE_URL` is also set (prod signal).

External adapters (Vault, AWS SM, GCP SM) plug in as new resolvers without touching loaders or writers.

### Connection type ↔ Source/Destination compatibility

Enforced in the API save layer (`SOURCE_CONNECTION_COMPAT` / `DESTINATION_CONNECTION_COMPAT` maps in `dte/models/pipeline.py`). Mismatched combinations (e.g. an s3 source bound to a postgres connection) → 422 on POST/PUT.

### Test endpoint

`POST /api/connections/{id}/test` — lightweight connectivity probe. Returns `{ok: bool, elapsed_ms: int, detail: str}`. Per-type probes in `dte/sources/connection_test.py`. UI shows the result inline on `/connections`.

### Migration

Legacy plan-015 sources/destinations (creds inline in `config`) migrate via `backend/scripts/migrate_extract_connections.py`. Extracts unique cred blobs into Connection rows (sha1-deduped), rewrites source/dest configs to reference by id. `filesystem`/`json_file`/`csv_file` all share a singleton `local_fs_default` connection. Idempotent.

## First-class sources and destinations

Sources and destinations are stored independently of pipelines. Pipelines reference them by id: `Pipeline.sources: list[str]` and `Pipeline.output_id: str`. Both sides get their own store protocol (`SourceStore`, `DestinationStore` in `backend/dte/store/base.py`), memory + Postgres implementations, and CRUD API routes.

- `Source` (renamed from `DltSource`) — `id`, `source_type`, `config`, `table`, `format`. `DltSource` remains as a deprecated alias for one release. `format` is a top-level nullable column (migration `009`) — one of `json`/`jsonl`/`ndjson`/`csv`/`parquet`/`excel`, or NULL for auto-detect from the glob extension. Only meaningful for filesystem-family kinds. On save, `Source` rejects `format` that lives in a different reader family than the glob's trailing extension (e.g. `format=excel` + `*.csv` → 422); same-family mismatches like `format=jsonl` + `*.json` pass through, preserving the "wrong extension, right content" escape hatch.
- `Destination` — `{id, config: OutputTarget}` where `OutputTarget` is the existing discriminated union (`json_file` | `csv_file` | `excel_file` | `parquet_s3` | `postgres` | `sql_database`). File-shaped targets (`json_file`, `csv_file`, `excel_file`, `parquet_s3`) enforce that the on-disk extension matches the target family — a `json_file` at `orders.csv` is rejected at save (422), same for missing extensions. `.jsonl`/`.ndjson` are accepted for `json_file` (same family). Non-file destinations (`postgres`, `sql_database`) are unaffected.
- Pipeline execution (`preview`, `trigger`) resolves each source id via `SourceStore.get` and the destination id via `DestinationStore.get` before compiling. Missing id → 422 naming what's missing.
- `compile_pipeline(pipeline, tables, output=None)` — the compiler is source-agnostic; the caller passes the resolved `OutputTarget` if it needs the output-fields projection.
- Legacy embedded pipelines migrate via `backend/scripts/migrate_embedded_endpoints.py`: extracts every embedded `Source` and `output` into their own tables (generated dest id: `<pipeline_id>_output`), rewrites the pipeline. Idempotent.
- Module rename: `dte.sources.dlt_loader` → `dte.sources.loader`. A `dlt_loader` shim re-exports for one release.
- Alembic `004` creates the `sources` and `destinations` tables. Shape: `id text PK`, `source_type`/`dest_type text`, `config jsonb`, plus `table_name` on sources.

## API surface

```
POST   /api/pipelines                     create pipeline (validates source/dest ids exist)
GET    /api/pipelines                     list pipelines
GET    /api/pipelines/{id}                get pipeline
PUT    /api/pipelines/{id}                update pipeline
DELETE /api/pipelines/{id}                delete pipeline
POST   /api/pipelines/{id}/trigger        start async run → {run_id}
GET    /api/pipelines/{id}/preview?limit  compile + execute on sample rows
GET    /api/pipelines/{id}/runs?limit     run history per pipeline
GET    /api/runs/{run_id}                 poll run status
GET    /api/runs/{run_id}/output?limit    peek at the run's output file
POST   /api/schema/infer                  field tree from an in-flight Source body
POST   /api/sources                       create source (409 on id collision)
GET    /api/sources                       list sources
GET    /api/sources/{id}                  get source
PUT    /api/sources/{id}                  update source
DELETE /api/sources/{id}                  409 with {referenced_by: [...]} if any pipeline uses it
GET    /api/sources/{id}/schema           field tree for a saved source (id-only)
POST   /api/destinations                  create destination
GET    /api/destinations                  list destinations
GET    /api/destinations/{id}             get destination
PUT    /api/destinations/{id}             update destination
DELETE /api/destinations/{id}             409 with {referenced_by: [...]} if any pipeline uses it
POST   /api/connections                   create connection (409 on id collision; creds encrypted at rest)
GET    /api/connections                   list connections (credentials masked)
GET    /api/connections/{id}              read (?reveal=true for plaintext creds)
PUT    /api/connections/{id}              update (empty credentials keeps existing)
DELETE /api/connections/{id}              409 with {referenced_by: {sources, destinations}} if in use
POST   /api/connections/{id}/test         connectivity probe → {ok, elapsed_ms, detail}
```

`Run` responses include `id`, `pipeline_id`, `status` (`pending`/`running`/`completed`/`failed`), `error`, `rows_written`, `started_at`, `finished_at`. Per-step run events are **not** recorded yet — the frontend `Timeline` renders an empty state placeholder.

`finished_at` is written by the Postgres store, not the API code. Migration `003` installs a `BEFORE UPDATE` trigger on `runs` that stamps `finished_at = NOW()` when `status` becomes `completed` or `failed`. `MemoryRunStore.update` mirrors the rule. If you introduce a new terminal status, extend both.

## Development workflow

### Before implementing any feature

Write a plan to `plans/<NNN>-<feature-name>.md`. Plans must include: problem statement, architecture change, explicit task list with branch names, and files changed/deleted. See existing plans for format.

### Worktree workflow (required for all feature work)

```bash
# Start
git worktree add ./worktrees/<name> -b feature/<name>

# Work in worktree, run tests
cd backend && uv run pytest -x

# Merge back
cd /Users/bhavaniravi/projects/dte
git merge feature/<name> --no-ff
git worktree remove worktrees/<name>
git branch -d feature/<name>
```

Every non-trivial change gets its own worktree. Do not develop directly on `main`.

## Store / database

**Postgres-only** — there is no in-memory production path. `DATABASE_URL` must be set; getters in `dte/api/deps.py` raise `RuntimeError` if it's missing. Tests inject `Fake*Store` implementations from `tests/fakes.py` via `app.dependency_overrides` (an autouse conftest fixture attaches them, plus a pre-seeded `local_fs` connection so most tests don't need boilerplate). Both Postgres stores hold a session factory (not a live session) so the singleton is safe across FastAPI requests and the background `asyncio.create_task` in `trigger_pipeline`.

Under Docker Compose, `DATABASE_URL=postgresql+asyncpg://dte:dte@postgres:5432/dte` is set on the backend service. The compose command runs `alembic upgrade head` first (using a synced URL derived by stripping `+asyncpg`) and then execs uvicorn. Pipelines persist across `docker compose restart` via the `pgdata` volume.

Postgres integration tests (`tests/integration/test_store_postgres.py`) are skipped automatically when `DATABASE_URL` is unset. When enabled, they use an `async_sessionmaker` fixture and pass it to the store constructors — mirror this pattern in any new integration test.

### Model + store pattern (SQLModel)

Every Pydantic-modelled persisted entity — `Pipeline`, `Source`, `Destination`, `Connection` — is a triple in `dte/models/pipeline.py`:

- `XxxBase(SQLModel)` — API/domain fields + Pydantic validators. No persistence identity.
- `Xxx(XxxBase, table=True)` — adds `id`, `created_at`, `updated_at`, plus persistence-only columns (e.g. `Connection.credentials_encrypted`, `Destination.dest_type`).
- `XxxCreate(XxxBase)` — the FastAPI request body. `id: str` is required here; `table=True` bypasses required-field checks so it can't play that role.

**SQLModel 0.0.39 gotchas hit by this codebase:**

- `Literal[...]` types on a `table=True` class break the metaclass (it calls `issubclass(Literal, Enum)`). Workaround: type as `str` on `Base` with `sa_column=Column(Text, ...)`, then override with the `Literal` on `Create` for strict API-edge validation. See `ConnectionBase.connection_type` vs `ConnectionCreate.connection_type`.
- `table=True` maps every inherited field to a column — there's no `sa_column=None` escape. For attributes you want in the API model but *not* persisted (e.g. `Connection.credentials`, plaintext), define them only on `Base` / `Create` and let the store attach them to `Xxx(table=True)` instances as plain Python attributes via `object.__setattr__` after decrypt/hydration. Read via a helper (`Connection.credentials_dict()`).
- `table=True` construction skips Pydantic validators. For hydrated instances that need post-load massage (e.g. `Destination.config` narrowed from a JSONB dict to the discriminated `OutputTarget` union), the store calls an explicit method — `Destination.narrow_config()` uses `TypeAdapter(OutputTarget).validate_python(...)` — before returning the row. Do NOT rely on validators to fire on ORM hydration.

**Store shape.** Every `Postgres*Store` (except `PostgresRunStore`) uses the same three-verb ORM template — see `PostgresPipelineStore` as the canonical example:

- `get(id)` → `session.get(Xxx, id)`
- `save(create)` → `pg_insert(Xxx).values(**create.model_dump(...)).on_conflict_do_update(...)` — the `on_conflict_do_update` form is required (not `session.merge`) because `updated_at` has an `onupdate=func.now()` server default that `merge` won't trigger
- `list(...)` → `select(Xxx).order_by(Xxx.created_at.desc())`

Fakes (`tests/fakes.py`) store typed instances too — they mimic the same protocol shape. Some fakes accept `dict` inputs for legacy migration-script compatibility; new tests should always pass typed `XxxCreate` instances.

## TDD convention

Write failing tests first. Implement until they pass. Stop — do not add features beyond what tests require.
