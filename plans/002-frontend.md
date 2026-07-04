# Plan 002 — Frontend (Next.js)

## Problem

DTE currently only exposes a FastAPI. Pipeline authoring requires hand-writing JSON and hitting endpoints with `curl`. There is no way to see what pipelines exist, trigger runs, or inspect run status without shelling into the API.

## Goal

A Next.js app that covers both roles:

1. **Builder** — a form-based editor for `Pipeline` JSON (sources, ordered steps, output). Not a canvas/graph editor in v1; a typed step-list editor that mirrors the Pydantic discriminated unions.
2. **Monitor** — list pipelines, trigger runs, view run status and errors.

Deferred out of v1: auth, multi-user, drag-and-drop DAG canvas, run history filtering, live log streaming (poll instead), Postgres source (backend supports it, UI limited to `json_file`/`csv_file` for now).

## Architecture

```
frontend/                             # Next.js 15 App Router, TS, Tailwind, shadcn/ui
  app/
    layout.tsx
    page.tsx                          # pipeline list
    pipelines/
      new/page.tsx                    # builder — create
      [id]/page.tsx                   # pipeline detail + run history + trigger
      [id]/edit/page.tsx              # builder — edit
    runs/
      [id]/page.tsx                   # run detail (polls status)
  lib/
    api.ts                            # typed fetch client
    types.ts                          # generated from OpenAPI (openapi-typescript)
  components/
    builder/
      SourceEditor.tsx
      StepEditor.tsx                  # dispatches on op + mode
      steps/{Filter,Rename,Retype,LookupMap,ExpressionMap,Sort,Aggregate}.tsx
      OutputEditor.tsx
      PipelineForm.tsx                # composes the above
    RunStatusBadge.tsx
```

**API contract.** Types are generated from FastAPI's `/openapi.json` via `openapi-typescript` into `lib/types.ts`. The fetch client in `lib/api.ts` wraps `fetch` and uses those types. No hand-written type duplication.

**CORS.** FastAPI needs `CORSMiddleware` allowing `http://localhost:3000` in dev.

**State.** Server components for reads (pipeline list, pipeline detail); client components for the builder form and run polling. `useSWR` for run status polling (2s interval until terminal).

**Styling.** Tailwind + shadcn/ui (Form, Input, Select, Button, Card, Badge, Dialog). No custom design system in v1.

**Backend runs on** `:8000`, **frontend on** `:3000`. `NEXT_PUBLIC_API_URL` env var, defaults to `http://localhost:8000`.

## Tasks

Each task = one branch = one worktree = one focused PR.

### Task 1 — `feature/frontend-scaffold`
- Create `frontend/` with `create-next-app` (TS, Tailwind, App Router, no src dir).
- Install shadcn/ui, initialize with a couple of base components (button, input, card, badge, form, select).
- Install `openapi-typescript`, `swr`, `zod`, `react-hook-form`, `@hookform/resolvers`.
- Add npm scripts: `dev`, `build`, `lint`, `gen:types` (runs openapi-typescript against a running API).
- Add `CORSMiddleware` to `dte/api/main.py` for `http://localhost:3000`.
- Land `lib/api.ts` skeleton and empty `app/page.tsx` that lists no pipelines yet (calls `GET /api/pipelines` — see task 2 for endpoint).
- **Files changed:** `frontend/**` (new), `dte/api/main.py`.

### Task 2 — `feature/api-list-pipelines`
Backend prerequisite. `GET /api/pipelines` (list) is needed by the UI but doesn't exist yet.
- Add `list_pipelines()` route returning `list[Pipeline]` from the in-memory store.
- Add `list_runs(pipeline_id?)` route returning runs, optionally filtered.
- Tests in `tests/unit/test_api_routes.py` for both.
- **Files changed:** `dte/api/routes/pipelines.py`, `dte/api/routes/runs.py`, `tests/`.

### Task 3 — `feature/frontend-pipeline-list-and-detail`
- `app/page.tsx` — server component, fetch and render pipeline cards.
- `app/pipelines/[id]/page.tsx` — pipeline detail: sources summary, step count, output path, "Trigger run" button (client component), recent runs list.
- `RunStatusBadge` component.
- **Files changed:** `frontend/app/**`, `frontend/components/RunStatusBadge.tsx`.

### Task 4 — `feature/frontend-run-monitor`
- `app/runs/[id]/page.tsx` — client component using `useSWR` to poll `GET /api/runs/{id}` every 2s until status ∈ {completed, failed}.
- Show status, rows_written, error stack if failed.
- **Files changed:** `frontend/app/runs/**`.

### Task 5 — `feature/frontend-builder`
- `PipelineForm` with `react-hook-form` + Zod schemas mirroring the Pydantic models.
- `SourceEditor` — add/remove sources; support `json_file` and `csv_file` in v1.
- `StepEditor` — an ordered list of steps with add/remove/reorder (up/down buttons, no DnD yet). Dispatches to a per-op sub-editor based on `op` (and `mode` for `map`).
- Individual step editors matching each Pydantic model.
- `OutputEditor` — path + fields list.
- Submits to `POST /api/pipelines`.
- Edit route reuses the same form with initial values from `GET /api/pipelines/{id}`.
- **Note:** `PUT /api/pipelines/{id}` doesn't exist backend-side; edit will need a small backend task or POST-with-same-id (in-memory dict overwrite works). Decide during implementation.
- **Files changed:** `frontend/components/builder/**`, `frontend/app/pipelines/new/**`, `frontend/app/pipelines/[id]/edit/**`, possibly `dte/api/routes/pipelines.py`.

### Task 6 — `feature/frontend-readme-and-scripts`
- Update root `CLAUDE.md` with frontend commands section.
- Add `frontend/README.md` with dev flow.
- **Files changed:** `CLAUDE.md`, `frontend/README.md`.

## Deleted files
None.

## Open questions (decide during implementation, not blocking)
- Do we want a "dry run" endpoint that compiles without executing, so the builder can validate before save? Nice-to-have — defer unless task 5 exposes a strong need.
- Should the step editor allow raw JSON escape hatch per step? Probably yes as a `<details>` fallback so power users aren't blocked by missing UI fields.
