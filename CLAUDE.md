# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repo layout

```
backend/       Python package `dte`, alembic, tests, Dockerfile
frontend/      Next.js app
docker-compose.yml   whole stack (postgres + backend + frontend)
plans/         feature plans (numbered)
marketing-plans/  go-to-market plans (numbered) — ICP, motion, pricing, content
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

# Per-op scenario suite (opt-in; excluded from default collection)
uv run pytest tests/scenarios -m scenario -v

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

### Information hierarchy rules

Design rules for anything user-facing live in **`frontend/DESIGN.md`**. Read it
before changing layout, adding a panel, or deciding where something goes on a
page — it carries the ordering principles, the precedents behind them (each
with the bug that produced it), and the checklist for new surfaces.

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

`components/builder/sources/` — the multi-type source editor. Per-kind config editors: `filesystem` (bucket_url/directory + file_glob), `sql_database` (connection_string + table/query), `mongodb` (connection_url + database + collection). Adding a new kind means: add to `SOURCE_KINDS`, add a `CONFIG_TEMPLATES[kind]`, write a `<Kind>SourceEditor.tsx`, dispatch in `SourceEditor.tsx`. `filesystem`'s `bucket_url` must be a **directory** — the label + hint explicitly say so; users hit this repeatedly if the hint is softened. `documents` (PDF) gets its own editor with no format dropdown: listing only stats files, so a reader format would be a control that does nothing.

`bucket_url` and `file_glob` are whitespace-trimmed on save (`SourceBase._validate_config`) and again in `_glob_local`. A trailing space survives copy-paste, is invisible in the input, and turns a correct glob into `No files matched '**/*.pdf '` — an error that reads as if the pattern were wrong.

A blank `id` on any of `Connection`, `Source`, `Destination`, `LookupTable` means server-generated. `default_factory` alone does not achieve this — it fires only when the key is **absent**, so `{"id": ""}` from a form would otherwise be written as an empty primary key, producing a row that saves but cannot be referenced. `_blank_id_means_generate` strips the blank key first.

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
                   # |"check"|"profile"|"extract"|"structure"
mode = step.get("mode")   # "lookup"|"expression"|"calculation"  — map steps only
```

### Unstructured: documents, extract, structure (plan 050)

A `documents` source lists files — path, size, modified time — and **parses
nothing**. Extraction happens only when an `extract` step runs, which is what
keeps `POST /api/schema/infer` instant and free while the builder fires it on
every edit.

```
documents source → extract (PDF → text) → structure (text → typed columns)
                                        → every existing step works from here
```

- **`extract`** fans one document out to one row per page (`granularity`).
  Providers: `pdfplumber` (word bounding boxes, needed for provenance
  highlighting) and `pypdf` (faster, text only). A document that fails to
  parse fills `extract_meta.error` and leaves the text NULL — it does **not**
  fail the run. Add a `check` step if you want it fatal.
- **`structure`** turns text into the user's declared fields as real typed
  columns. Providers: `claude`, `openai`, and `regex` (deterministic, free,
  offline, exact provenance — and the only one CI can run).

**These two ops break laziness.** Every other step is a lazy ibis expression;
a model call cannot be. They go through `BaseEngine.apply_enrichment`
(`dte/engine/base.py`), which materialises, maps in Python, and registers the
result back — the same shape as `_apply_check_step` and `_apply_profile`.
`TrinoEngine` raises `EnrichmentNotSupportedOnBackend`.

**Caching is the whole economic argument.** Extract results are keyed by
document content; structure results by `sha256(text)` + the entire structure
config. So downstream steps (`select`, `filter`, `aggregate`) are free to
iterate on, and editing a prompt never re-parses a PDF. But there is no
partial reuse: changing one field's description re-calls the model for every
field on every row. Artifacts are never garbage-collected today.

`DTE_ARTIFACT_DIR` **must** point at storage shared by the API and the
workers. It defaults to the relative `.dte-artifacts`, which resolves inside
each container — backend and worker then keep separate caches and Trigger
re-pays for what Preview bought. Compose mounts a named volume; the Dockerfile
creates the directory owned by `dte` so the fresh volume inherits that
ownership (a root-owned volume fails silently for the non-root process).

**Document inspector** (`/documents/[key]`, and the Inspect action on run
output / preview rows). An extracted row carries three distinct references and
you need all three: `artifact_ref` is the *document* hash, `extract_meta.key`
is the *derived* key holding the cached parse (word boxes, page size), and
`structure_meta.fields` holds per-field provenance. A doc hash cannot be
turned back into a derived key — that needs the provider and every param — so
`/documents/[key]` shows the document alone; highlights need the row, which is
why the table action opens a modal instead of navigating.

Highlight geometry (`frontend/src/lib/provenance.ts`) deliberately ignores
`char_start`/`char_end`. Those index into `page.extract_text()` while boxes
come from `page.extract_words()` — two independent pdfplumber passes with no
guaranteed alignment, so trusting them yields highlights that are subtly off,
which is worse than none: it looks authoritative while pointing at the wrong
number. The quote is matched against the word sequence instead, anchored at
word boundaries, normalising away everything but letters and digits (the page
reads `$1,240.50`; a model quotes `1240.50`). No match → no box, and the UI
says so.

`tests/fixtures/pdf_builder.py` must emit one text operator **per line**. A
newline inside a single `Tj` is not a line break in PDF — pdfplumber decodes
it as `(cid:10)` glued into the neighbouring word, word segmentation
collapses, and every highlight silently fails to resolve.

The artifact route serves **ranged streams** (`Accept-Ranges`, 206, streamed
from `store.open_stream`). pdf.js is opened with `disableAutoFetch` so it
fetches only the pages viewed — without that flag it backgrounds a fetch of
the whole file and the range support buys nothing. `Content-Range` is in CORS
`expose_headers`; omit it and pdf.js silently reverts to whole-document
downloads, which still works and so never surfaces as an error.

**Optional extras**: `[unstructured]` is pypdf + pdfplumber; `[models]` is the
anthropic + openai SDKs. Both are lazy imports, so a missing extra surfaces
only on a real run, never in tests.

**API keys** currently come from `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in the
environment, wired to both `backend` and `worker`. Do **not** put a key in the
step's `params.api_key`: step params are stored unencrypted in
`pipelines.steps` JSONB and copied into every revision. See
`plans/052-model-provider-connections.md`.

### Eval harness (plan 051)

**Scoring core.** `dte/evals/` — `comparators.py` and `scoring.py`. Pure
functions, no I/O, no storage. Comparators are forgiving on formatting and
strict on semantics (`$1,240.50` matches `1240.5`; `1240.50` does not match
`1204.50`). Metrics are precision/recall/F1, never accuracy, and correct
abstention (`tn`) is counted separately from a silent miss (`fn`) — without
that split an extractor that answers nothing scores well.

**Storage** (migration `034`). `eval_sets` holds a labeled corpus for one
extraction task; `eval_examples` holds one labeled document per row. Models in
`dte/models/eval.py`, stores in `dte/store/postgres.py`, protocols in
`store/base.py`, fakes in `tests/fakes.py`.

- **`doc_key` is `sha256(document bytes)`** — the same key the plan-050
  artifact store uses. Labels therefore survive renames and directory moves,
  and join directly against extraction output with no path matching. The model
  rejects anything that isn't a 64-char hex digest: a filename here would join
  against nothing and the set would score a permanent zero with no error.
- **`eval_examples` is upserted on `(eval_set_id, doc_key)`, not on `id`.**
  The natural identity of a label is the document it labels; without the
  UNIQUE constraint, relabeling appends a contradictory second row that then
  gets scored twice.
- **`labels_version` is owned by `bump_labels_version`, never by `save`.**
  Every label write bumps it and runs pin what they scored against, so folding
  it into `save` would let a rename invalidate every historical score. The
  Postgres increment happens in SQL — two concurrent labelers must not both
  read 3 and both write 4.
- **`field_specs` is the scorer's own model.** `EvalSetBase.to_field_specs()`
  is the single conversion, and an unknown comparator type is rejected at save
  time — a bad comparator must fail when the set is created, not at the end of
  a paid sweep.
- **Five new `runs` columns**: `eval_set_id`, `labels_version`,
  `config_digest`, `sweep_id`, `scores`. All nullable with no default —
  "never scored" must stay distinguishable from "scored zero". `runs` is raw
  SQL with no SQLModel, so the select list now lives in one constant
  (`_RUN_COLUMNS`) and the jsonb write set in another (`_RUN_JSONB_COLUMNS`);
  adding a column means editing those two plus the migration. It used to be
  duplicated across `get` and `list_for_pipeline`, where a column added to one
  and forgotten in the other simply vanished from that read path.
- `eval:read` / `eval:write` / `eval:delete` are granted to the seeded roles
  by migration `034` itself. Adding a value to `Permission` in code only
  changes what *may* be checked; the `roles` table holds what is granted.

**The run path.** `pipeline_type: "eval"` pipelines go through the eval branch
of `_run_body`: compile → materialise → join to labels on `doc_key` → score →
persist. Scoring lives in the runner, not the compiler, mirroring
`evaluate_contracts` — precision/recall over a corpus *is* an aggregation, and
`_validate_steps` rejects `aggregate` outside transform pipelines.

- **`artifact_ref` is `artifact://<sha256>`, `doc_key` is the bare digest.**
  `_doc_key_from_ref` strips the scheme. Without it every join misses, the
  corpus scores a flat zero, and nothing errors.
- **`FieldMetrics.f1` is `2tp/(2tp+fp+fn)`**, not the harmonic mean of
  precision and recall. Precision is undefined when an extractor answers
  nothing, so the harmonic form returned `None` for a total failure — which
  renders as "unrated" and drops out of ranking exactly like an unscored set.
- Eval and quality pipelines both have **no destination**. Anything gating on
  `output_id` (the builder's save validation, its schema-inference effect)
  needs to allow both or an eval pipeline cannot be saved or edited.

**Labeling** — four paths, all writing through `EvalExampleStore.save`, all
bumping `labels_version`:

- `POST /eval-sets/{id}/examples:import` (CSV/JSONL), `.../bootstrap`
  (consensus over N variants), `.../propose` (LLM judge), and the
  **inspector's Correct / Fix buttons**, which are the highest-leverage path
  because the reviewer is already comparing the value to the page.
- **`consensus()` requires unanimity, uses the eval set's own comparators, and
  refuses to treat unanimous null as agreement.** All three matter: majority
  voting among variants sharing a model counts one opinion twice; string
  equality would route a currency corpus into review; and a null label asserts
  the right answer is *nothing*, after which every abstaining extractor scores
  a hit. The review UI must agree with this — a variant's miss is never
  offered as a pickable label, and "document doesn't state this" is a separate,
  explicit option.
- Variants sharing a `provider` block auto-accept (409). Judge labels are
  permanently tagged; the leaderboard's >50% warning depends on the tag.

**Sweeps.** `POST /eval-sets/{id}/sweep` with `confirm=false` estimates and
enqueues nothing. Confirmed, each cell becomes a **real pipeline and run** via
`start_eval_run` — the same path a manual trigger uses. `dte/evals/sweep.py`:

- `detached_copy` rebuilds from `model_dump()` rather than `copy.deepcopy`. A
  pipeline loaded from Postgres is SQLAlchemy-instrumented; deep-copying it
  and assigning `.id` raises `ObjectDereferencedError`. The fakes return
  detached instances, so this passes every unit test and 500s in production.
- `variant_id` is derived from the config digest, so relaunching a sweep
  reuses rows and hits the extract cache instead of re-paying under a new name.
- An unknown matrix axis **raises**. Dropping a typo silently yields N
  identical cells scoring the same, which reads as "this setting makes no
  difference".

**Schedules** carry an optional `eval_set_id` (migration `035`) and the ticker
stamps it onto the run row, only when set. Validation at save time repeats the
trigger route's rules exactly — a schedule is a trigger on a timer, and a
disagreement between the two surfaces at 2am. No FK: deleting an eval set a
schedule references returns 409 naming the schedules.

**Frontend** — `/eval-sets` (list, with best-F1 and last-run), `/eval-sets/new`
(create) and `/eval-sets/[id]` (Leaderboard / Examples / Review).
`pipeline_type` includes `"eval"` in `api.ts`, the builder, and `StepsPanel`
(which hides `aggregate`/`pivot` — they would collapse the rows the labels
join against). `/eval-sets` is a **server component**: never
`toLocaleDateString()` there, it hydration-mismatches.

**Three objects, and "eval" used to name two of them.** An **eval set** is the
labeled corpus (`/eval-sets`); an **eval pipeline** is an extraction config
under test (`/pipelines?type=eval`); an **eval run** is one scoring of one
pipeline against one set at one `labels_version`. The route was `/evals` while
the nav also carried "Eval" for pipelines — two different objects a letter
apart. The frontend route now matches the model, the table and the API, all of
which were already `eval_set(s)`; `next.config.ts` keeps a permanent redirect
from `/evals/*`.

Anything user-visible that filters by `pipeline_type` must come from
`PIPELINE_TYPE_TABS` (`lib/pipeline-type.ts`), which drives the sidebar and
the list page together. Eval pipelines shipped creatable and reachable from
nowhere because the nav and the page each knew about a different subset of
types, and an unrecognised `?type=` silently means "no filter".

### Compare: the entry point to the harness (plan 053)

**Start from the pipeline, not the eval set.** Reaching a provider
comparison through plan 051's surfaces took 28 steps minimum and could not
be completed in the UI at all. The object model was fine; the entry point
was wrong. `/eval-sets/new` asked users to declare a source and retype a
field list their pipeline already carried — so `CompareButton` on
`/pipelines/{id}` derives all of it:

```
POST /pipelines/{id}/as-eval          → the eval twin (idempotent)
POST /eval-sets:for-pipeline          → the eval set   (idempotent)
POST /eval-sets/{id}/sweep            → estimate, then confirm
GET  /sweeps/{id}/comparison          → the side-by-side view
```

- **`dte/evals/derive.py` maps `model.fields` → `field_specs`.** One-way
  only. The two shapes are close but unequal (`comparator` on one side,
  `pattern`/`required`/`examples` on the other) and a two-way sync between
  them is how the drift the derivation removes would return.
- **The eval-set id carries a fingerprint** of field names, comparator
  types and comparator options — *not* order and *not* descriptions.
  Reordering fields and rewording a prompt hint are the edits people make
  constantly while iterating; minting a fresh set for either would discard
  every label collected so far. Two pipelines extracting the same fields
  from the same corpus therefore share one set, which is what lets claude
  and openai appear on one leaderboard.
- **The twin normalises sweepable keys** (`params.model`,
  `model.instructions`). `apply_cell` refuses to *create* a leaf that does
  not exist, and that guard is what stops a typo'd axis becoming N
  identical cells reading as "this setting makes no difference" — so the
  twin is filled in rather than the guard loosened.

**The comparison renders with no labels, and that is the point.** The
leaderboard's "No comparable runs yet" is a demand for work nobody has
done, and it is why the harness sat empty. `build_comparison`
(`dte/evals/comparison.py`) answers what needs no ground truth: per-field
agreement, cost, p95 latency, null rate, per-document values. Scores are
added when labels exist; **absent is the normal case, never an error, and
never rendered as zero**.

- Agreement rules are **imported from `bootstrap.py`**, not reimplemented —
  comparators not equality, null is not agreement, union not intersection.
  A comparison measuring agreement differently from the thing that writes
  labels would offer "accept 41 agreed" for a number the accept step
  refuses.
- `labels.auto_accept` reproduces bootstrap's shared-provider rule *in the
  payload*, because the UI must know before it offers the button. Sweeping
  models or prompts holds the provider fixed, so the 409 is the common
  case, and a primary button that fails on click is worse than a disabled
  one that explains.
- Rows are **re-materialised, not persisted** — an eval run writes no
  output. Affordable only because plan 050 caches by content hash; opening
  the page parses no PDF and calls no model.

**Shipping the winner is on the comparison, not only the leaderboard**
(plan 054). `promote` used to be rendered solely on the leaderboard, which
ranks *scored* runs — so the page that works without labels had no exit,
and the documented route out (accept labels → leaderboard → promote) is
refused outright whenever every config shares a provider, which is what a
model or prompt sweep produces. `PromoteFromComparison` puts one
`Ship a config…` in the summary bar and chooses the config inside the form.

- **One control, not one per cell.** The promote form does not fit a 220px
  card, and Promote is the page's exit rather than a property of a cell —
  by the time it is reached the decision is made.
- **Nothing is preselected.** Unlabelled, the page computes no ranking;
  labelled, it computes ties rather than winners. A default would assert
  what neither state supports.
- **Unshippable cells stay in the list with the reason attached**
  (`lib/comparison-shippable.ts`). The one that matters: a run whose every
  call failed is `completed` and green, because `on_error: null` fills
  nulls rather than failing — shipping it ships empty columns. A missing
  option reads as a bug; "every row errored" is the useful thing to say.
- `PromoteForm` is shared with the leaderboard. Two implementations would
  drift, and the drift is invisible until a promoted pipeline stops
  matching the digest that was measured.

**`regex` is gated on patterns** (`lib/compare-matrix.ts`). Without a
`pattern` per field the provider returns nothing on every row and the cell
scores ~0 — which reads as "regex is bad at this" rather than "regex was
never configured". The chip is disabled and names the fields that lack one.

Also fixed here, all three previously invisible: OpenAI models were
unpriced (and one unpriced row nulls a whole run's cost by design);
`eval_max_sweep_cells` was read off a `Settings` that never declared it, so
`DTE_EVAL_MAX_SWEEP_CELLS` was inert; and the sweep skipped the
corpus-match check `trigger` enforces — now `validate_eval_corpus_match`,
called by both, before the estimate rather than at confirm.

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

POST   /api/eval-sets                     create eval set
GET    /api/eval-sets                     list (+ best_macro_f1, last_run_at)
GET/PUT/DELETE /api/eval-sets/{id}        read / update / delete (409 if scheduled)
POST   /api/eval-sets/{id}/examples       upsert one label on (eval_set_id, doc_key)
GET    /api/eval-sets/{id}/examples       list labels
DELETE /api/eval-sets/{id}/examples/{eid} remove a label
POST   /api/eval-sets/{id}/examples:import CSV/JSONL bulk import
POST   /api/eval-sets/{id}/bootstrap      consensus over N variants (confirm to write)
POST   /api/eval-sets/{id}/propose        LLM-judge labels (confirm to write)
POST   /api/eval-sets/{id}/sweep          estimate, then confirm to enqueue one run/cell
POST   /api/eval-sets/{id}/promote        copy a winning config into a transform pipeline
GET    /api/eval-sets/{id}/leaderboard    ranked runs; ties within the Wilson interval
GET    /api/eval-sets/{id}/fields/{f}/failures  expected-vs-got for one field

POST   /api/pipelines/{id}/as-eval        eval twin of a pipeline (idempotent)
POST   /api/eval-sets:for-pipeline        eval set derived from a pipeline (idempotent)
GET    /api/sweeps/{sweep_id}/comparison  configs side by side; works with no labels
```

`Run` responses include `id`, `pipeline_id`, `status` (`pending`/`running`/`completed`/`failed`), `error`, `rows_written`, `started_at`, `finished_at`. Per-step run events are **not** recorded yet — the frontend `Timeline` renders an empty state placeholder.

`finished_at` is written by the Postgres store, not the API code. Migration `003` installs a `BEFORE UPDATE` trigger on `runs` that stamps `finished_at = NOW()` when `status` becomes `completed` or `failed`. `MemoryRunStore.update` mirrors the rule. If you introduce a new terminal status, extend both.

## Development workflow

### Before implementing any feature

Write a plan to `plans/<NNN>-<feature-name>.md`. Plans must include: problem statement, architecture change, explicit task list with branch names, and files changed/deleted. See existing plans for format.

Go-to-market plans (ICP, positioning, pricing, channels, content) live in `marketing-plans/` instead — same numbering, no branch names or task lists. If a document has a buyer, a channel, or a price, it belongs there. Start with `marketing-plans/README.md`.

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

### Setting up a fresh worktree

A new worktree is a checkout of tracked files only, so everything ignored or
generated is missing. Four things, and each fails in a way that does not name
the real cause:

```bash
cd worktrees/<name>
cp ../../.env .                      # 1
cd frontend && pnpm install          # 2
pnpm exec next typegen               # 3
cd ../backend && uv venv && uv pip install -e ".[dev]"   # 4
```

1. **`.env` is gitignored, so a new worktree has none.** Compose reads `.env`
   from the directory you invoke it in — not from the repo root — so a stack
   started in a fresh worktree comes up with nothing set and the backend dies
   on `RuntimeError: DTE_JWT_SECRET must be set when DATABASE_URL is set
   (production)`. The message describes the symptom, not the cause: the file
   is simply absent. `.env.example` is committed; the real one is not.
   Copy it, and never commit the copy — `.gitignore:13` covers `.env` but
   **not** `.env.*`, so a `.env.bak` is a secrets file git can see.
2. Missing `node_modules` surfaces as `Cannot find module 'pdfjs-dist'` from
   `tsc` — which reads as a broken import, not a missing install. The same
   applies to any checkout whose `node_modules` predates a new dependency,
   `main` included.
3. `PageProps` / `LayoutProps` are Next 16 **generated globals**. Without
   `next typegen` (or a `dev`/`build` run) `tsc` reports
   `Cannot find name 'LayoutProps'` in files nobody touched.
4. No venv means `uv run pytest` fails with `Failed to spawn: pytest`.

### Docker from a worktree

**Always run compose from the worktree you are working in**, and keep
`-p dte` so the `dte_pgdata` and `dte_artifacts` volumes are reused:

```bash
cd worktrees/<name> && docker compose -p dte up -d
```

Compose bind-mounts `./backend/dte`, `./backend/alembic` and `./frontend`
**relative to the invocation directory**, so the directory you type this in
decides which code runs. Two ways that bites:

- Starting the stack from a directory whose `alembic/versions` lags the
  database fails with `Can't locate revision identified by '0NN'` and the
  backend exits — alembic walks *forward* from the DB's current revision, and
  a revision the script directory has never heard of is unreachable. Running
  from `main` while the DB is at a feature branch's migration does this.
- A stack left running from another directory silently serves *that* code.
  The frontend is the confusing one: features vanish from the UI with no
  error anywhere.

`docker inspect <container> --format '{{index .Config.Labels
"com.docker.compose.project.working_dir"}}'` says which directory a running
container was started from — check it first when the UI and the code
disagree.

## Store / database

**Postgres-only** — there is no in-memory production path. `DATABASE_URL` must be set; getters in `dte/api/deps.py` raise `RuntimeError` if it's missing. Tests inject `Fake*Store` implementations from `tests/fakes.py` via `app.dependency_overrides` (an autouse conftest fixture attaches them, plus a pre-seeded `local_fs` connection so most tests don't need boilerplate). Both Postgres stores hold a session factory (not a live session) so the singleton is safe across FastAPI requests and the background `asyncio.create_task` in `trigger_pipeline`.

Under Docker Compose, `DATABASE_URL=postgresql+asyncpg://dte:dte@postgres:5432/dte` is set on the backend service. The compose command runs `alembic upgrade head` first (using a synced URL derived by stripping `+asyncpg`) and then execs uvicorn. Pipelines persist across `docker compose restart` via the `pgdata` volume.

Postgres integration tests (`tests/integration/test_store_postgres.py`) are skipped automatically when `DATABASE_URL` is unset. When enabled, they use an `async_sessionmaker` fixture and pass it to the store constructors — mirror this pattern in any new integration test.

### Alembic backfills

Any backfill that could touch > 100k rows **must** use `dte.alembic_util.batched_update` — never a bare `UPDATE ... SET ...` or a `for row in session.query(...)` loop inside a migration. The helper runs each batch in its own AUTOCOMMIT transaction so a killed migration leaves committed batches on disk, and uses `FOR UPDATE SKIP LOCKED` to coexist with concurrent OLTP writers. See `plans/032-batched-alembic-backfills.md`.

### Model + store pattern (SQLModel)

Every Pydantic-modelled persisted entity — `Pipeline`, `Source`, `Destination`, `Connection` — is a **two-class** pair in `dte/models/pipeline.py`:

- `XxxBase(SQLModel)` — API/domain fields + Pydantic validators. `id: str` is required here so FastAPI raises 422 on missing. Carries the API-strict Literal types (e.g. `connection_type: ConnectionType`, `source_type: SourceKind`) — Pydantic rejects unknown values at the edge. Routes bind POST/PUT bodies to `XxxBase`.
- `Xxx(XxxBase, table=True)` — persistence identity (overrides `id: str = SMField(primary_key=True)`), timestamp columns, and Literal overrides to plain `str` (SQLModel 0.0.39 can't map Literal to a SA column). Stores save and return typed `Xxx` instances.

Back-compat aliases `XxxCreate = XxxBase` are kept for one release so existing migration scripts don't break.

**`EncryptedJSON` TypeDecorator** (`dte/secrets/encrypted_json.py`) — used for `Connection.credentials`. Maps the logical Python `dict` to a BYTEA column (`credentials_encrypted`), transparently calling `get_secret_resolver().encrypt()` on write and `.decrypt()` on read. `PostgresConnectionStore` needs no `SecretResolver` injection — encryption happens at the column level. Physical column name unchanged; no migration required.

**SQLModel 0.0.39 gotchas hit by this codebase:**

- `Literal[...]` types on a `table=True` class break the metaclass (it calls `issubclass(Literal, Enum)`). Workaround: keep the strict `Literal` on `Base` for API validation; override with `str` + an explicit `sa_column=Column(Text, ...)` on the table class. Both classes now live together without a third `Create` class.
- `table=True` construction skips Pydantic validators. For hydrated instances that need post-load narrowing (e.g. `Destination.config` narrowed from a raw JSONB dict to the discriminated `OutputTarget` union), the store calls an explicit method — `Destination.narrow_config()` uses `TypeAdapter(OutputTarget).validate_python(...)` + `object.__setattr__` to bypass SA instrumentation. Do NOT rely on validators to fire on ORM hydration. `Connection.credentials` no longer needs this because `EncryptedJSON` handles the round-trip at the TypeDecorator level.

**Store shape.** Every `Postgres*Store` (except `PostgresRunStore`) uses the same three-verb ORM template — see `PostgresPipelineStore` as the canonical example:

- `get(id)` → `session.get(Xxx, id)`
- `save(base)` → `pg_insert(Xxx).values(**base.model_dump(exclude={timestamps})).on_conflict_do_update(...)` — the `on_conflict_do_update` form is required (not `session.merge`) because `updated_at` has an `onupdate=func.now()` server default that `merge` won't trigger
- `list(...)` → `select(Xxx).order_by(Xxx.created_at.desc())`

Fakes (`tests/fakes.py`) store typed `Xxx` instances and accept `XxxBase | Xxx | dict` at `save()` (dict for legacy migration-script compat). New tests should always pass typed `XxxBase` instances.

## Testing tiers

Three tiers, each with a distinct purpose. Run only what the change touches.

- **Unit** (`backend/tests/unit/`) — compiler + model tests, no HTTP, no I/O. Fast. Collected by default `pytest`.
- **Integration** (`backend/tests/integration/`) — hits real Postgres via `DATABASE_URL`; auto-skips when unset. Marker: `integration`.
- **Scenarios** (`backend/tests/scenarios/`) — end-to-end user flows over the real HTTP API using `httpx.AsyncClient(ASGITransport)`. One file per step op under `steps/`, plus `test_error_paths.py`, `test_nested_fields.py`, `test_preview_endpoint.py`. Marker: `scenario`. **Excluded from the default `pytest` run** via `addopts = "--ignore=tests/scenarios"` in `pyproject.toml` — opt-in with `pytest tests/scenarios -m scenario`.

Scenario suite conventions:
- Fixtures: `client` (async), `scenario_ids` (unique id minter + reverse-dep teardown), `fixtures_dir`, `out_dir` (writes to `tmp_path`, never into the repo). See `tests/scenarios/conftest.py`.
- DSL in `tests/scenarios/helpers.py`: `create_connection`, `create_source`, `create_destination`, `create_pipeline`, `create_lookup_table`, `trigger_and_wait`, `read_output_file`.
- Deterministic hand-crafted fixtures (`orders.json`, `products.json`, `customers.json`, `nested_orders.json`, `orders_with_null.json`) — exact-match row-set assertions.
- **macOS/arm64 quirk**: sync `TestClient` spins a fresh anyio portal thread per test; successive DuckDB→Arrow-string casts segfault across threads. Fix baked into conftest: use `httpx.AsyncClient` + `ASGITransport` so everything runs on one asyncio loop.
- **JSON writer quirk**: `dte/engine/writers/json_file.py` uses `json.dumps(..., default=str)`; DuckDB `SUM(int) → DECIMAL` and `int * 1.1 → DECIMAL` land as strings. Scenario tests coerce with `float(...)`.

When adding scenario coverage: match the async fixture set, xfail (with a `reason=` pointing at the bug) if a test uncovers a real regression — do not fix compiler code inside a test PR.

## TDD convention

Write failing tests first. Implement until they pass. Stop — do not add features beyond what tests require.
