## Frontend

An **Airflow `react_apps` plugin** (plan 066): React **19** + TypeScript + Tailwind **v4**, built by **Vite** into one UMD bundle, `dist/dte.umd.js`. Package manager is **pnpm**. There is no Next.js and no iframe — Airflow `import()`s the bundle and renders its default export inside Airflow's own page.

### How it runs

- `backend/dte/airflow/plugin.py` registers four `react_apps` entries (DTE + three under Admin), all pointing at `/dte/ui/dte.umd.js`, which the API serves from `backend/ui` (`Dockerfile.airflow` copies `dist/` there).
- Airflow puts `React`, `ReactDOM`, `ReactJSXRuntime` and `ReactRouterDOM` on `globalThis`. `vite.config.ts` marks them external and maps them to those globals — **never bundle React**: a second copy breaks every hook. The `output.intro` `require` shim exists because bundled CJS deps (`use-sync-external-store`, via swr + recharts) keep a literal `require("react")`; without it the plugin fails with `require is not defined` and Airflow shows its 404 page (its loader falls back to that on any load error).
- Dev loop: `pnpm dev` (= `vite build --watch`), then `docker cp dist/dte.umd.js dte-airflow-apiserver-1:/opt/dte/backend/ui/` and reload `/plugin/dte`. There is no standalone dev server — the bundle needs Airflow's globals.
- Same origin as Airflow: `apiFetch` calls `/dte/api/...` with Airflow's session cookie.

### Routing

- Airflow mounts plugins at `plugin/:page/*`. `src/plugin.tsx` holds the route table (paths relative to that base) and picks the landing section from `:page` (`dte` → pipelines, `dte-sources` → sources, …).
- `src/lib/nav.tsx` gives Next-shaped `Link` / `useRouter` / `usePathname` / `useSearchParams` over react-router, adding and stripping the `/plugin/<page>` base — so page code writes app-absolute paths (`/pipelines/detail?id=x`). Use it; importing `react-router-dom` directly means handling the base yourself. `router.refresh()` revalidates every SWR key.
- **No DTE sidebar** (plan 067): Airflow's rail is the only nav. Airflow 3.3 groups same-category plugin items under the rail's **Plugins** menu, so Transform (`dte`) and Quality Check (`dte-quality`, which just redirects to the filtered list) appear under Plugins ▸ DTE Pipelines. Sources, Destinations and Lookup tables are Admin-menu entries (`dte-sources`, …).
- **Every entry shares one bundle.** Airflow 3.3 clears `globalThis.AirflowPlugin` before each `import()` and looks the component up at `globalThis[<react_app name>]`, and the browser runs the cached bundle only once, so `plugin.tsx` registers `DtePlugin` under every name in `ENTRY_NAMES`. A new entry in `plugin.py` needs its name added there (`test_plugin_names.py` fails otherwise). Keep `plugin.tsx`'s only export the default: a named export turns the UMD global into a module object. `nav.tsx` mounts an absolute href under the page that _owns_ its section (`OWNED`), not the current page, so cross-section links move the rail highlight. A new owned section = a `plugin.py` entry + an `OWNED` prefix.
- **DTE Run tab** (`destination: "dag_run"`, `url_route: dte-run`): Airflow shows it on every dag run page at `dags/:dagId/runs/:runId/plugin/dte-run` and passes `{dagId, runId}` as props, with no `?id=`. `plugin.tsx` registers `DteRunTab` under that name instead of `DtePlugin`; it renders `RunDetail` with `embedded` (no Topbar/PageHeader, since Airflow already shows the run header) for `dte__*` DAGs, and a note for every other DAG.
- Pipeline types in the UI come from `PIPELINE_TYPE_TABS` (Transform, Quality Check), shared by the list toggle and the builder picker. Eval and Visualize are hidden, and so are eval sets and dashboards: their components remain but are unrouted. They are still in the API.
- Pages live in `src/pages/` and route by query string (`detail?id=`), not path segments.
- `window.history.replaceState` must pass `window.history.state`, not `null` — react-router keeps its index there and `null` breaks Back.

### Design system (portable)

- `src/components/ui/` imports only from itself + `@/lib/cn.ts`. Anything in `src/components/builder/` is DTE-specific.
- **The theme is Airflow's.** Tokens in `src/dte.css` are scoped to `.dte-root` and defined as Airflow's Chakra variables (`--bg: var(--chakra-colors-bg)`, `--accent: var(--chakra-colors-brand-fg)`, …), remapped into Tailwind's `@theme` (so `bg-surface`, `text-muted`, `border-border` work). Chakra switches those variables on `html.dark`, so DTE follows Airflow's light/dark toggle and any configured theme with no JS. DTE has no theme toggle of its own.
- **Nothing may style outside `.dte-root`.** The stylesheet is injected into Airflow's `<head>`: no Tailwind preflight, no `html`/`body` rules. Airflow's Chakra reset covers what preflight did.
- `text-accent` is brand **fg** (readable text); filled controls use `bg-accent-solid text-accent-contrast` — Airflow's own solid-button pair. Don't put `text-white` on an accent fill.
- Fonts are Airflow's: `font-ui` = `--chakra-fonts-body` (Inter), `font-mono` = `--chakra-fonts-mono`, `font-brand` (the `dt·e` wordmark only) = `--chakra-fonts-heading`.
- The chart palette (`--chart-1..6`) is the one exception: DTE's own validated sets, light on `.dte-root`, dark on `.dark .dte-root`.
- Every color the app uses (including status pills, run tones, code bg) comes from tokens. Don't hardcode hex values in components.

### Design vocabulary (`components/ui/`)

`Button` (variants: default/primary/ghost × sm/md, optional `kbd`), `Pill` (`ok`/`running`/`failed`/`pending`), `Panel` + `PanelHead`, `PageHeader`, `SectionHead`, `Topbar`, `DataTable<T>` (client), `StepRow`, `ExprCode`/`ExprToken`, `KV`/`KVItem`, `AddStep`, `Item`, `Tag`, `Metric` + `MetricRow`, `Timeline` + `TimelineRow` + `InlineCode`, `Field`/`Input`/`Textarea`/`Segmented`, `FieldPicker`, `FieldMultiSelect`. Re-exports through `components/ui/index.ts`.

### Information hierarchy rules

Design rules for anything user-facing live in **`frontend/DESIGN.md`**. Read it
before changing layout, adding a panel, or deciding where something goes on a
page — it carries the ordering principles, the precedents behind them (each
with the bug that produced it), and the checklist for new surfaces.

### API client + typegen

- `src/lib/api-types.ts` is generated from the running API's `/openapi.json`: `DTE_API_URL=http://localhost:8080/dte ./scripts/gen-api-types.sh`.
- `src/lib/api.ts` is the hand-written wrapper: `apiFetch<T>`, named helpers (`listPipelines`, `getPipeline`, `createPipeline`, `updatePipeline`, `deletePipeline`, `triggerPipeline`, `previewPipeline`, `listPipelineRuns`, `getRun`, `inferSchema`), `Run` type (backend returns dict; typed here), `isTerminal`, `isJsonFileOutput` narrower.
- SWR wired in `src/lib/swr-config.tsx` with `fetcher: (path) => apiFetch(path)`. `refreshInterval` on the run page uses `(latest) => isTerminal(latest?.status) ? 0 : 2000`.

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

### Dialect feedback + expression recipes

Both live on the raw-SQL inputs (`MapExpressionEditor`, and the Advanced tab
of Filter and Check). Neither is a step, and neither persists anything of its
own.

- **Feedback** rides `POST /pipelines/step-schemas`, which the builder already
  debounce-fetches on every edit — no new endpoint and no extra request.
  `AutoStepSchemas` lives once in `components/pipeline/schema-sync.tsx` and is
  used by both hosts; `useStepFeedback()` reads it per step index and renders
  `DialectReadback`: what the target database receives, its own error attached
  to the step that caused it, and any known meaning-change. Silent for DuckDB.
- **Recipes** (`lib/expression-recipes.ts`) are fill-in-the-slots shapes that
  _generate_ a fragment into the existing `expr`. One direction only — no
  parse-back and no Basic/Advanced mode, because here the fragment is the
  artifact and a mode that had to re-parse arbitrary SQL would either lie or
  refuse to open. The list only offers expressions measured to survive
  transpilation (see `backend/CLAUDE.md`); a test asserts the known hard
  failures cannot appear in it.
- SQL composed from user input goes through `lib/sql-literal.ts`
  (`quoteIdent` / `quoteString` / `safeLiteral`) — never string concatenation.

### When adding a new step op

1. Backend: add `Xxx` Pydantic model in `dte/models/pipeline.py`, dispatch in `dte/compiler/ibis_compiler.py`, add compiler tests first.
2. Regenerate `frontend/src/lib/api-types.ts` (see _API client + typegen_).
3. Frontend: extend `StepOp` + `STEP_OPS` + `emptyStep()` in `components/builder/steps/types.ts`.
4. Write `XxxEditor` in `editors.tsx`; dispatch from `StepEditor` at the bottom. Use `useSchemas().allFields` for any field references.
