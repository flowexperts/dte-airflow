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

- `BuilderForm` wraps everything in `<SchemaProvider>` and validates on submit: id required + alphanumeric/`_`/`-`, name required, output path required, no empty-`fields` select step.
- `StepsPanel` owns the ordered list, reorder (↑/↓ buttons), remove, and an "Add step" menu keyed off `STEP_OPS`.
- Every op has a dedicated editor in `components/builder/steps/editors.tsx` — one file so the dispatch is easy to read. Each editor emits the exact dict shape the backend expects.
- `Rename`, `MapLookup.table`, and `Select` maintain local UI state that syncs to the parent's parsed form via a `useEffect` guarded by shallow equality — needed so mid-typing (`"customer_id →"` with no RHS yet) isn't wiped by the parser.
- `Filter` has **Basic** / **Advanced** tabs. Basic composes DuckDB SQL with `quoteIdent`/`safeLiteral` — identifiers wrapped in `""` (internal `"` → `""`); values dispatched: bare ints/floats pass through, `true`/`false` pass through as booleans, everything else becomes a `''`-quoted string with internal `'` → `''`. Zero SQL injection surface in Basic. Advanced is raw SQL and the hint says so.
- `Select` step (op `select`) is the projection editor. Two modes on `Segmented`: **Keep** (chip picker + optional aliases) and **Drop** (chip picker of what to strip). Drop mode is fully derived: a `useEffect` on `(mode, dropped, allFields)` sets `fields = allFields − dropped`, so switching to Drop mode with a schema immediately populates the keep set. If schema is missing, an inline "infer schema first" placeholder shows instead.
- **Nested fields.** dlt flattens nested JSON with `__` (`order.amount` → `order__amount`). Every schema-aware editor passes `variant="tree"` to `FieldPicker`/`FieldMultiSelect`, which renders `FieldTreePicker` — a collapsible tree with dot-form leaf labels but wire-form (`__`-joined) values on the step. `components/ui/field-tree.ts` is the transform seam (`toDisplay`, `toWire`, `buildTree`, `findNode`). Reserved `_dlt_*` names stay as flat top-level leaves.

### Output — discriminated union

Backend `output` is now a Pydantic discriminated union over `type`: `json_file` | `csv_file` | `parquet_s3` | `postgres` | `sql_database`. The UI **only edits `json_file`** today. `isJsonFileOutput(pipeline.output)` narrows before reading `.path`. `BuilderForm` shows a placeholder card for other types. When adding an output editor, follow the same pattern: narrow with the type guard, don't add optional chaining to bypass the union.

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

**`dte/sources/dlt_loader.py`** — universal source loading via dlt. `load_source(DltSource, ibis_con)` runs a dlt pipeline into the shared DuckDB connection (`con.con` is the raw `duckdb.DuckDBPyConnection`) and returns an `ibis.Table`. Currently implements `filesystem` source type; add new source types here. Do **not** write custom connector classes — extend this file with new dlt sources.

**`dte/compiler/ibis_compiler.py`** — `compile_pipeline(pipeline, tables)` maintains a **named registry** (`dict[str, ibis.Table]`) instead of a rolling variable. Each step reads from and writes back to the registry via `current_key`. Join steps write their result under `output_id` and update `current_key`. This allows multi-source pipelines.

- Filter and expression-map steps escape to raw SQL via `con.create_view()` + `con.sql()` — Ibis has no SQL string parser. This is the seam for future distributed backends (Spark, Trino).
- Pivot uses `con.con.execute("CREATE OR REPLACE TEMP TABLE ... AS PIVOT ...")` — dynamic PIVOT cannot be a view in DuckDB, and `con.sql()` fails because sqlglot can't subquery a PIVOT node.

**`dte/engine/duckdb_engine.py`** — wraps `ibis.duckdb.connect()`. Exposes `con` property (the ibis backend) for use by `dlt_loader`. Only responsible for execution and output — does not load sources.

**`dte/store/`** — `PipelineStore` and `RunStore` Protocols in `base.py`. `memory.py` is the default (used in all tests). `postgres.py` is the production backend (SQLAlchemy async, requires `DATABASE_URL`). The active backend is wired in `dte/api/deps.py` and injected into routes via FastAPI `Depends()`.

**`dte/api/`** — FastAPI app. Routes use `Depends(get_pipeline_store)` and `Depends(get_run_store)`. Tests override these with `app.dependency_overrides`. `_execute_pipeline` runs as an `asyncio.create_task` — trigger returns `run_id` immediately, caller polls `GET /api/runs/{run_id}`.

### Step dispatch

```python
op = step["op"]    # "filter"|"rename"|"retype"|"map"|"sort"|"aggregate"|"join"|"pivot"|"select"
mode = step.get("mode")   # "lookup"|"expression"|"calculation"  — map steps only
```

### dlt column naming

dlt normalises nested JSON keys with `__` (e.g. `{"order": {"amount": 1}}` → column `order__amount`). `_resolve_field()` in the compiler falls back to `__`-joined names when struct traversal fails, making it compatible with both ibis struct columns and dlt-flattened columns.

### Ibis version notes

- ibis ≥ 9: use `ibis.cases(*[(condition, value), ...], else_=default)`, **not** `ibis.case()`
- `table.rename({new_name: old_name})` — ibis rename direction is reversed from intuition

## API surface

```
POST   /api/pipelines                     create pipeline
GET    /api/pipelines                     list pipelines
GET    /api/pipelines/{id}                get pipeline
PUT    /api/pipelines/{id}                update pipeline
DELETE /api/pipelines/{id}                delete pipeline
POST   /api/pipelines/{id}/trigger        start async run → {run_id}
GET    /api/pipelines/{id}/preview?limit  compile + execute on sample rows
GET    /api/pipelines/{id}/runs?limit     run history per pipeline
GET    /api/runs/{run_id}                 poll run status
POST   /api/schema/infer                  field tree from a DltSource config
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

`dte/api/deps.py` picks the backend at import time: if `DATABASE_URL` is set, it constructs `PostgresPipelineStore`/`PostgresRunStore` with an `async_sessionmaker` singleton; otherwise it falls back to the in-memory stores. Both Postgres stores hold a session factory (not a live session) so the singleton is safe across FastAPI requests and the background `asyncio.create_task` in `trigger_pipeline`.

Under Docker Compose, `DATABASE_URL=postgresql+asyncpg://dte:dte@postgres:5432/dte` is set on the backend service. The compose command runs `alembic upgrade head` first (using a synced URL derived by stripping `+asyncpg`) and then execs uvicorn. Pipelines persist across `docker compose restart` via the `pgdata` volume.

Postgres integration tests (`tests/integration/test_store_postgres.py`) are skipped automatically when `DATABASE_URL` is unset. When enabled, they use an `async_sessionmaker` fixture and pass it to the store constructors — mirror this pattern in any new integration test.

## TDD convention

Write failing tests first. Implement until they pass. Stop — do not add features beyond what tests require.
