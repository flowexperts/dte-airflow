@AGENTS.md

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


