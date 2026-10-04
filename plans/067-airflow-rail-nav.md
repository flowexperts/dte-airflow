# Plan 067 — Airflow's left rail replaces DTE's sidebar

## Context
DTE renders inside Airflow (plan 065; plan 066 is moving it from an iframe to a native
`react_apps` bundle and is in progress in this checkout). DTE still draws its own
220px sidebar next to Airflow's rail, so there are two navigation columns. The sidebar has
already lost Connections, Dashboards and Eval sets. What remains is four links to
pipeline types, a brand mark and a user footer.

Goal: remove the DTE sidebar and move its job into Airflow's rail, so there is one way
around. Decisions made with the user:
- One top-level rail item, **"DTE Pipelines"**.
- Sources, Destinations and Lookup tables stay under **Admin**, next to Connections.
- **No** DAG or DAG-run tabs. New pipelines are still created from DTE Pipelines → New
  pipeline.
- Eval sets and Dashboards are **removed from the UI**. The **Eval and Visualize pipeline types
  are hidden** too, since they depend on those pages. Backend and data are untouched.

Checked in the running Airflow 3.1.8:
- A nav item with no category gets its own rail icon; `category: "admin"` puts it in the
  Admin menu.
- `icon` and `icon_dark_mode` take an image URL.
- Airflow's route is `plugin/:page/*`, so sub-paths reach the bundle.

## Resulting flow
```
Airflow rail
  Home · Dags · Assets · Browse · Admin · [DTE Pipelines]
                                  │
             Admin ▸ Connections, Sources, Destinations, Lookup tables

DTE Pipelines  /plugin/dte/pipelines
  header: [Transform | Quality Check]   (segmented, drives ?type=)   [New pipeline N]
  row → /pipelines/detail?id=…  (builder, runs, schedules; crumb "DTE Pipelines › Transform › name")
      → run → /runs/detail?id=…
  source/destination/lookup links → jump to /plugin/dte-sources/… (Admin highlights)
```
Nothing that is still offered becomes harder to reach:
- The type links move from the sidebar into the list header.
- Identity and logout are in Airflow's User menu.
- System health is on Airflow's Home page.

## Tasks (worktree `feature/airflow-rail-nav`, after plan 066 lands)
1. **Plan:** write `plans/067-airflow-rail-nav.md` (this plan).
2. **`backend/dte/airflow/plugin.py`:**
   - Rename the top entry to `"DTE Pipelines"`.
   - Add `icon` and `icon_dark_mode` pointing at `/dte/ui/icon.svg` and `/dte/ui/icon-dark.svg`
     (new files in `frontend/public/`, copied by the build).
   - The Admin entries stay; drop the "DTE " prefix only if it still reads clearly next to
     Airflow's items. Keep the prefix; it disambiguates "Sources".
   - Update the plugin-shape unit test.
3. **`frontend/src/plugin.tsx`:**
   - Delete the `AppSidebar` grid and the `ADMIN_SECTIONS` branch; always render
     `<main>{routes}</main>`.
   - Remove the routes `eval-sets*`, `dashboards*` and `pipelines/compare` (sweep compare is
     eval-only).
4. **Cross-section links, in `frontend/src/lib/nav.tsx` only.** `join()` currently prefixes the
   *current* `/plugin/<page>`, so a pipeline → source link would open Sources under the
   Pipelines rail item. Make it pick the owning page by path prefix: `/sources` →
   `dte-sources`, `/destinations` → `dte-destinations`, `/lookup-tables` → `dte-lookup-tables`,
   everything else → `dte`. Every `Link` and `router.push` routes through this, so it is one
   fix for every caller.
5. **Pipeline types:**
   - In `frontend/src/lib/pipeline-type.ts`, cut `PIPELINE_TYPE_TABS` to Transform and
     Quality Check.
   - In `components/builder/BuilderForm.tsx:182`, take the builder's `Segmented` options from
     `PIPELINE_TYPE_TABS` instead of its own literal list, so the two can't drift again.
   - Leave `parsePipelineType` accepting eval/viz so existing links don't 404 into a wrong
     filter.
6. **List header:**
   - In `frontend/src/pages/pipelines/index.tsx`, add the existing `Segmented` component (from
     `components/ui`) bound to `?type=`, with `PIPELINE_TYPE_TABS`. It replaces the sidebar
     links.
   - With no `?type=`, default to Transform. Eval/viz pipelines are then hidden, as decided.
7. **Crumbs:**
   - Replace the dead root crumb `{ label: "Workspace", href: "/" }` (about 17 call sites) with
     the section's rail name: "DTE Pipelines" for pipeline and run pages, "Admin" with no link
     for sources, destinations and lookups.
   - Do it with a mechanical find-and-replace. Files under `pages/eval-sets` and `dashboards`
     aren't routed any more, so skip them.
8. **Delete:**
   - `components/app-sidebar.tsx`, and the parts of `components/ui/sidebar.tsx` only it used
     (Sidebar, Brand, NavItem, NavGroup…). Check with a search first.
   - `pages/eval-sets/`, `pages/dashboards/` and `pages/pipelines/compare.tsx` (the page
     wrappers only; the components they render are still imported by the pipeline detail
     page for existing eval pipelines, so leave those).
   - Fix the one comment in `new-resource-button.tsx` that references AppSidebar.
9. **Docs:**
   - `frontend/CLAUDE.md` nav section: the rail is Airflow's, the owning-page rule is in
     `nav.tsx`, and eval/viz are hidden.
   - README feature table: mark Eval and Visualize as API-only for now.

Skipped:
- DAG and run tabs (user declined).
- Deep links into Airflow's DAG pages from DTE rows. Add a "View in Airflow" link on the
  pipeline detail if people ask for it.

## Verification
- `cd frontend && pnpm typecheck && pnpm test && pnpm build`
- `cd backend && uv run pytest -q -m "not integration"`
- `docker compose up -d --build`, then in Chrome at `localhost:8080` (admin/admin):
  - The rail shows "DTE Pipelines" with its icon in both colour modes, and there is no
    second sidebar anywhere.
  - Pipelines list: the Transform/Quality toggle filters and updates `?type=`; New pipeline
    → save → Run → run detail all work.
  - In the builder, a source link opens `/plugin/dte-sources/...` and Admin is highlighted.
    Browser back returns to the builder.
  - Admin ▸ Sources/Destinations/Lookup tables open full-width.
  - `/plugin/dte/eval-sets` and `/plugin/dte/dashboards` fall through to the pipelines
    list.
- `./scripts/e2e-airflow.sh` still prints `E2E OK`.

## Revision — upgrade to Airflow 3.3.2 for a native menu
The user wanted a click-to-open menu for DTE's pipeline types. In 3.1.8, only
the built-in Browse, Admin, Docs and User groups get menus. 3.3.2 groups
same-category plugin items under a rail **Plugins** button
(`layouts/Nav/PluginMenus.tsx`). The rail labels are still one line.

- The nav is now Plugins ▸ DTE Pipelines ▸ Transform (`dte`) / Quality Check
  (`dte-quality`, which redirects to `?type=quality`).
- Image `apache/airflow:3.3.2-python3.12`. Its constraints pin `sqlglot==30.18`,
  which nothing in the image uses and which breaks ibis raw SQL on Postgres, so
  the Dockerfile drops that one pin.
- ibis 11 → 12: 3.3.2 ships pandas 3, and ibis 12 is the first release that
  accepts it. Under pandas 3 a missing string is `NaN`, not `None`. Production
  reads rows through `to_json` and `to_pylist`, so it is unaffected; two tests
  were fixed.
- The image's `cryptography` (≥47, bundled OpenSSL) crashes with SIGILL under
  Docker on Apple Silicon (M4). Compose sets `OPENSSL_armcap=0`.
- `get_user()` renamed `oauth_token`, so `dte/airflow/auth.py` now passes the
  arguments by position.
- 3.3 clears `globalThis.AirflowPlugin` before each bundle import, so
  `plugin.tsx` registers the component under every react_app name
  (`test_plugin_names.py`).
