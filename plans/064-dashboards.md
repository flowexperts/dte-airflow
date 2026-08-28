# Plan 064 — Dashboards

## Context

Today the only thing a pipeline can do with its result is **write it
somewhere** — a file, a bucket, a table. Every pipeline is required to name an
`output_id`, and the only way to *look* at data is the builder's Sample rows
table (20–100 rows, monospace, no aggregation legible at a glance).

Users connecting a source want the last mile too: *see* the numbers. That is a
dashboard — same sources, same steps, but the terminal act is a visualization
rather than a write.

**Do we need a new view/table?** For the *data path*, no — and this is the part
worth being lazy about. `GET /api/pipelines/{id}/preview`
(`dte/api/routes/pipelines.py:1002`) already compiles a saved pipeline inline
and returns rows as JSON, writing nothing:

```python
df = compiled.limit(limit).execute()
rows = json.loads(df.to_json(orient="records", date_format="iso"))
return {"rows": rows, "count": len(rows), "step_sqls": ..., "final_sql": ..., "error": ...}
```

That endpoint is the dashboard data API. No new execution path, no new engine
method, no `/dashboards/{id}/data` route — each tile fetches its own pipeline's
preview via SWR, which also buys per-tile loading/error states for free.

For *layout*, yes — a new `dashboards` table, because a multi-tile dashboard
composes N pipelines and there is nowhere on a pipeline to put "tile 3 is a
half-width bar chart". (Decision confirmed with the user over the
one-chart-per-pipeline alternative.)

Outcome: `/dashboards` in the nav; a dashboard holds tiles; each tile points at
a pipeline and a chart spec; opening it renders live charts off `preview`.

---

## Architecture

```
sources ─→ pipeline (pipeline_type="viz", output_id=None)
                   │
                   │  GET /api/pipelines/{id}/preview?limit=N   ← already exists
                   ▼
dashboards table ─→ tile { pipeline_id, chart: {kind,x,y[],series}, w,h }
                   ▼
        <Tile> ──SWR──→ <Chart> (recharts)
```

Two independent halves. The `viz` pipeline type is what removes the "you must
invent a destination to draw a chart" friction; the `dashboards` entity is the
layout. Tiles may point at *any* pipeline, viz or transform.

---

## Backend

### 1. `viz` pipeline type — output-less pipelines

`dte/models/pipeline.py:~1370` — extend the discriminator:

```python
pipeline_type: Literal["transform", "quality", "eval", "viz"] = "transform"
```

`dte/api/routes/pipelines.py` currently repeats
`getattr(p, "pipeline_type", "transform") in ("quality", "eval")` at **five**
sites (lines ~227, 285, 354, 825, 1025 — validate refs, trigger, compile,
dry-run, preview). Replace all five with one module-level predicate:

```python
def _requires_output(p) -> bool:
    return getattr(p, "pipeline_type", "transform") not in ("quality", "eval", "viz")
```

Five copies is how the next type ships half-working.

**Bug to fix in the same commit** — `PostgresPipelineStore.save`
(`dte/store/postgres.py:115-131`) upserts with an explicit
`set_={name, sources, steps, output_id, engine, quality_contracts, params}`.
`pipeline_type` and `matrix` are written on INSERT and **silently dropped on
UPDATE**. So converting an existing pipeline to `viz` via `PUT` appears to
succeed and does nothing. Add both to `set_`.

Frontend counterpart: add `{ type: "viz", label: "Visualize" }` to
`PIPELINE_TYPE_TABS` in `frontend/src/lib/pipeline-type.ts` (and its `KNOWN`
array + `PipelineTypeFilter` union) — the file's own comment explains that a
type absent from this list is creatable and reachable from nowhere.

### 2. Models — new file `dte/models/dashboard.py`

`models/pipeline.py` is already ~1600 lines; a new entity gets its own module.
Follow the `LookupTableBase` / `LookupTable(table=True)` pair at
`dte/models/pipeline.py:614-661` exactly (uuid4 default id, `_blank_id_means_generate`,
`tenant_id: str = "default"`, JSONB `sa_column`s, `created_at`/`updated_at`).

```python
class ChartSpec(BaseModel):
    kind: Literal["bar", "line", "area", "pie", "number", "table"]
    x: str | None = None          # category / time axis field
    y: list[str] = []             # one or more value fields
    series: str | None = None     # group-by field → one line/bar colour per value
    stacked: bool = False
```

**The chart spec is presentational only — it never aggregates.** Grouping and
summing are what the `aggregate` step already does; a second aggregation engine
inside the chart layer would drift from the compiler's semantics and be
unpreviewable. A tile whose pipeline returns 50k raw rows draws 50k points;
the fix is an `aggregate` step, and the tile editor should say so.

```python
class DashboardTile(BaseModel):
    id: str = SMField(default_factory=lambda: str(_uuid.uuid4()))
    title: str
    pipeline_id: str
    chart: ChartSpec
    width: Literal[4, 6, 12] = 6   # columns in a 12-col grid
    height: Literal["s", "m", "l"] = "m"
    limit: int = SMField(default=1000, le=10_000)

class DashboardBase(SQLModel):
    id / name / description: str | None / tiles: list[DashboardTile] / tenant_id

class Dashboard(DashboardBase, table=True):
    __tablename__ = "dashboards"
```

`width`/`height` are enums, not free pixels — ordered tiles flowing in a 12-col
CSS grid, no absolute x/y. Free-form x/y requires collision handling and a drag
library to be usable, and buys nothing until someone asks.

Validators: `tiles` non-empty names unique; `chart.y` non-empty unless
`kind == "table"`; `kind == "number"` takes exactly one `y` and ignores `x`.

### 3. Store

- `DashboardStore` Protocol in `dte/store/base.py` — the same four methods as
  `PipelineStore` (`get/save/list/delete`), added to the `TYPE_CHECKING` import
  block.
- `PostgresDashboardStore` in `dte/store/postgres.py`, copied from
  `PostgresLookupTableStore` (tenant session via `_open_tenant_session`,
  `pg_insert(...).on_conflict_do_update`). **Every mutable column goes in
  `set_`** — `name`, `description`, `tiles`. See the pipeline-store bug above
  for what omitting one costs.
- `get_dashboard_store()` in `dte/api/deps.py`.
- `FakeDashboardStore` in `backend/tests/fakes.py` (dict-backed, mirrors the
  fake pipeline store).

### 4. Migration — `alembic/versions/038_dashboards.py`

`down_revision = "037"`. Template is `032_schedules.py` (table + indexes +
RLS), plus `034_evals.py` for the permission backfill.

```sql
CREATE TABLE IF NOT EXISTS dashboards (
    id          TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL DEFAULT 'default',
    name        TEXT NOT NULL,
    description TEXT,
    tiles       JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_dashboards_tenant_id ON dashboards (tenant_id);
ALTER TABLE dashboards ENABLE ROW LEVEL SECURITY;
ALTER TABLE dashboards FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON dashboards
  USING (tenant_id = current_setting('dte.tenant_id', true)::text);
```

**RLS is not optional here.** Without those three statements the table is
readable across tenants while `_open_tenant_session` still dutifully sets
`dte.tenant_id` — a silent isolation hole, since every query still returns
plausible rows.

**No FK on `tile.pipeline_id`** — tiles live inside JSONB, so Postgres cannot
enforce it. A deleted pipeline yields a dead tile; the UI renders "pipeline not
found" on that tile alone (see Frontend §3). *Skipped: the 409-on-delete guard
`lookup_tables.py:_referenced_by` uses. Add when someone actually loses a tile
they cared about.*

**Permission backfill in the same migration** (copy `034_evals.py:105-130`):
`dashboard:read` → admin/editor/viewer, `dashboard:write` → admin/editor,
`dashboard:delete` → admin. Role permissions are **rows in the `roles` table**
(`012_rbac.py:84`), not derived at runtime from
`dte/security/permissions.py` — so adding the strings to the `Permission`
Literal alone leaves every existing deployment 403ing on the new routes.

### 5. Routes — `dte/api/routes/dashboards.py`

Straight copy of `dte/api/routes/lookup_tables.py`'s shape, minus the
`_referenced_by` machinery:

| Method | Path | Perm |
|---|---|---|
| POST | `/dashboards` (201) | `dashboard:write` |
| GET | `/dashboards?limit&offset` | `dashboard:read` |
| GET | `/dashboards/{id}` | `dashboard:read` |
| PUT | `/dashboards/{id}` (path/body id must match) | `dashboard:write` |
| DELETE | `/dashboards/{id}` (204) | `dashboard:delete` |

Add `"dashboard:read" | "dashboard:write" | "dashboard:delete"` to the
`Permission` Literal in `dte/security/permissions.py:15` — the ADMIN/EDITOR/
VIEWER lists are computed from the `:read`/`:write` suffixes, so they need no
edit. Register the router in `dte/api/main.py` alongside the others
(`include_router(dashboards_router, prefix="/api", dependencies=_auth)`).

**No `/dashboards/{id}/data` route.** Tiles call the existing pipeline preview.

### 6. Backend tests (write first — TDD convention)

- `tests/unit/test_api_dashboards.py` — CRUD roundtrip via `FakeDashboardStore`;
  404 on unknown id; 400 on id mismatch; 403 for a viewer POSTing; validator
  rejections (empty `y` on a bar chart, two `y` on a `number`).
- `tests/unit/test_pipeline_viz_type.py` — a `pipeline_type="viz"` pipeline
  saves and previews with `output_id=None`; **PUT preserves `pipeline_type`**
  (regression for the `set_` bug — this one needs the real postgres store, mark
  `integration`).

---

## Frontend

### 1. Dependency + palette

`pnpm add recharts` (user's call over hand-rolled SVG). Recharts 3.x supports
React 19; pin whatever `pnpm add` resolves and confirm the app builds — a
React-19 peer warning here means stop and reassess before writing chart code.

Recharts takes colours as plain SVG attributes, and **CSS custom properties
work in SVG `fill`/`stroke`** — so `fill="var(--chart-1)"` themes for free with
no JS theme plumbing. Add `--chart-1..--chart-6` to both blocks of
`src/app/globals.css` next to the existing tokens.

**Load the `dataviz` skill before writing the first line of chart code** — it
carries the categorical-palette formula and the contrast validator these six
tokens must pass in light *and* dark.

### 2. `src/components/dashboard/chart.tsx` (`"use client"`)

One `<Chart spec rows />` switching on `spec.kind` →
`<ResponsiveContainer>` wrapping `BarChart` / `LineChart` / `AreaChart` /
`PieChart`. `number` and `table` are rendered without recharts (a big figure;
the existing `DataTable` from `components/ui`).

Beside it, `chartData(rows, spec)` — the one piece of real logic: pivots long
rows into recharts' wide shape when `spec.series` is set, coerces numeric
strings (preview JSON stringifies decimals), drops rows whose `x` is null.
**This gets the vitest** (`chart-data.test.ts`): long→wide pivot, numeric
coercion, empty input. Everything else is declarative JSX.

`components/ui/` may only import from itself + `lib/cn` — so this lives in
`components/dashboard/`, not `components/ui/`.

### 3. `src/components/dashboard/tile.tsx` (`"use client"`)

`<Panel>` + `<PanelHead label={tile.title}>` wrapping `<Chart>`, data from
`useSWR([tile.pipeline_id, tile.limit], () => previewPipeline(...))`. Four
states, all explicit: loading, `preview.error` (compile error → show it, it is
the actionable message), `404` on the pipeline (→ "pipeline deleted"), and
empty rows.

### 4. `src/components/dashboard/grid.tsx`

`grid-cols-12`; each tile `style={{ gridColumn: \`span ${tile.width}\` }}` with
a height class per `s|m|l`. Tiles flow in array order.

### 5. `src/components/dashboard/tile-editor.tsx`

Per-tile: pipeline picker (SWR `listPipelines`), title, `Segmented` chart kind,
`width`/`height` selects, and x/y/series field pickers. **Field options come
from the tile's own pipeline preview** — `Object.keys(rows[0])` filtered
through `visibleColumns()` (`src/lib/system-columns.ts`, which already strips
`_dlt_*`). No new schema endpoint; the preview call is already in flight.

Reorder with ↑/↓/× buttons, copying `components/builder/steps/StepsPanel.tsx`.
*Skipped: drag-and-drop layout. Add when tile counts pass ~8.*

### 6. Pages — `src/app/(app)/dashboards/`

`page.tsx` (list — `DataTable` + "+ New dashboard" primary button on the page,
not the nav), `new/page.tsx`, `[id]/page.tsx` (read-only grid + Edit),
`[id]/edit/page.tsx`.

Next 16 rules that bite here: `params` is a Promise (`await params` in the
server page, `use(params)` in a client one); **never pass a function from a
server page into a client component** — the list page's row-click and the
editor's handlers belong to `"use client"` sub-components the server page
composes. Read `frontend/DESIGN.md`'s "Checklist for a new surface" before
laying out the grid.

### 7. Nav + API client

- `src/components/app-sidebar.tsx`: `{can("dashboard:read") && <NavItem
  href="/dashboards" label="Dashboards" active={on("/dashboards")} />}` in the
  Workspace group, after Lookup tables.
- `src/lib/api.ts`: `listDashboards` / `getDashboard` / `createDashboard` /
  `updateDashboard` / `deleteDashboard`, matching the existing helper style.
- `DTE_API_URL=http://localhost:8001 ./scripts/gen-api-types.sh` with the
  backend running — never hand-edit `api-types.ts`.

---

## Task list (worktrees — no development on `main`)

| # | Branch | Scope |
|---|---|---|
| 0 | — | Copy this file to `plans/064-dashboards.md` |
| 1 | `feature/viz-pipeline-type` | `viz` type, `_requires_output` consolidation, `set_` bug fix, `PIPELINE_TYPE_TABS`, tests |
| 2 | `feature/dashboard-store` | `models/dashboard.py`, store + protocol + fake, migration 038 (table + RLS + perm backfill), tests |
| 3 | `feature/dashboard-api` | `routes/dashboards.py`, permissions Literal, main.py wiring, `gen-api-types.sh`, tests |
| 4 | `feature/dashboard-charts` | recharts, `--chart-*` tokens, `chart.tsx` + `chartData` + vitest, `tile.tsx` |
| 5 | `feature/dashboard-pages` | grid, tile editor, four pages, sidebar, api.ts helpers |

Tasks 1 and 2 are independent and can run in parallel; 3 needs 2; 4 needs 3
(for types); 5 needs 4.

---

## Verification

**Backend**

```bash
cd backend && uv run pytest tests/unit/test_api_dashboards.py tests/unit/test_pipeline_viz_type.py -v
uv run pytest -m "not integration"          # nothing else regressed
docker compose up -d --build && docker compose exec backend uv run alembic upgrade head
docker compose exec backend uv run alembic downgrade -1 && ... upgrade head   # migration reverses
```

Then confirm the permission backfill actually landed — the failure mode is a
403 on a fresh deployment, not a test failure:

```bash
docker compose exec postgres psql -U dte -c \
  "SELECT id, permissions FROM roles WHERE 'dashboard:read' = ANY(permissions);"
```

**End to end, in the app** (`docker compose up -d --build`, frontend on :3000):

1. Sources → connect the sample filesystem source (`backend/sample_data/`).
2. Pipelines → new, type **Visualize** → add an `aggregate` step (group by a
   category, count) → save **with no destination picked**. That save failing is
   the single sharpest check that task 1 worked.
3. Dashboards → new → add a tile → pick that pipeline → kind `bar`, x = the
   group field, y = the count → save.
4. Open `/dashboards/{id}`: the bar chart renders real numbers. Toggle the
   theme — bars and axes must both stay legible (the `--chart-*` tokens).
5. Add a second tile of kind `number` at width 4; confirm the grid reflows.
6. Delete the underlying pipeline; reload the dashboard: that tile alone says
   "pipeline not found", the other still renders.

**Frontend**

```bash
cd frontend && pnpm vitest run src/components/dashboard/chart-data.test.ts
pnpm build       # catches the server→client function-prop mistake
```

---

## Deliberately not in v1

- **Drag-and-drop layout** — ↑/↓ + three widths covers it. Add past ~8 tiles.
- **Aggregation in the chart spec** — the `aggregate` step already does it.
- **Scheduled refresh / caching** — tiles are live `preview` calls. Add when a
  tile is slow enough that someone complains.
- **409-on-delete for a pipeline a dashboard uses** — dead tiles are visible
  and recoverable.
- **Sharing / public dashboard links** — a whole auth surface of its own.
