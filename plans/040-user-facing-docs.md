# Plan: User-facing docs for DTE

## Context

DTE ships a visual pipeline builder (Next.js frontend on `:3000`, FastAPI backend on `:8001`) that lets a domain expert map a source → run it forever. Today the only user-facing text is the root `README.md` (a 40-line quickstart) — everything deeper (`ARCHITECTURE.md`, `plans/`, `docs/runbooks`, `CLAUDE.md`) is written for contributors and operators, not end users. New users landing on the app have no walkthrough of the connection → source → destination → pipeline → run flow, no reference for the ~9 step ops, and no per-connector config guide. Marketing has a landing page (`frontend/src/components/marketing/landing-page.tsx`) but no linked docs.

Goal: ship a small, focused **user documentation site** that (a) gets a new user to their first successful pipeline run in <10 minutes, and (b) serves as reference for every connector and step op. Screenshots are captured with Playwright against the local stack so they stay reproducible.

## Approach

**Where docs live:** `docs/user/` in this repo (keeps runbooks/observability separate under `docs/`). Author in Markdown so it renders on GitHub today; leave the door open to publishing via a Next.js `/docs` route later without a rewrite.

**Format:** plain Markdown + PNG screenshots in `docs/user/assets/`. No new toolchain, no MkDocs/Docusaurus for v1. Cross-links use relative paths so both GitHub and a future site work.

## Structure

```
docs/user/
  README.md                         # index / TOC
  getting-started/
    01-install.md                   # ./scripts/bootstrap.sh + docker compose up
    02-first-pipeline.md            # end-to-end walkthrough with screenshots
    03-concepts.md                  # Connection / Source / Destination / Pipeline / Run
  connections/
    index.md                        # what a connection is + test button
    filesystem.md                   # local_fs, no creds
    s3.md                           # httpfs, key/secret
    gcs.md                          # HMAC only (call out no service-account JSON)
    azure.md                        # connection_string or account+key
    postgres.md · mysql.md · sqlite.md · snowflake.md · bigquery.md
    mongodb.md · rest-api.md
  sources/
    index.md                        # kind + config + format override
    filesystem.md                   # bucket_url MUST be a directory; glob rules
    sql-database.md                 # table vs query
    mongodb.md · rest-api.md
  destinations/
    index.md                        # discriminated union overview
    json-file.md · csv-file.md · excel-file.md · parquet-s3.md
    postgres.md · sql-database.md
  pipelines/
    building.md                     # sources panel, destination picker, add step
    field-refs.md                   # dot syntax, nested structs, _dlt_* leaves
    preview-and-run.md              # preview button, trigger, run detail polling
    lookup-tables.md
  steps/
    index.md                        # table of all 9 ops
    filter.md                       # basic (safe SQL) vs advanced (raw)
    rename.md · retype.md
    map-lookup.md · map-expression.md
    sort.md · aggregate.md          # group_by incl. date-part extract
    join.md · pivot.md · select.md  # keep vs drop mode
  troubleshooting.md                # common errors surfaced in preview panel
  faq.md
```

## Content rules

- One page = one thing. Start with a one-line "what this is", then a screenshot, then the form fields as a table, then a minimal example.
- For each **connection type**: fields table, minimum required, a `.env` snippet or credential example, "test connection" expected result, common failure modes (link into `docs/runbooks/oncall/` where an ops-side runbook already exists e.g. `source-auth-spike.md`).
- For each **step op**: input schema, output schema, one screenshot of the editor, one worked example (before/after rows), any DuckDB SQL escape hatch notes (Filter Advanced, Map expression).
- Cross-link back to `README.md` quickstart and forward to `ARCHITECTURE.md` for readers who want internals.

## Screenshot pipeline (Playwright)

Add `docs/user/scripts/capture.ts` (Node, uses `@playwright/test` already familiar). One script, one array of `{route, name, actions?}`. Runs against `http://localhost:3000` after `docker compose up -d`. Writes PNGs to `docs/user/assets/<page>/<name>.png` at a fixed 1440x900 viewport with dark theme (matches the marketing site's default).

Seeding: reuse `backend/tests/scenarios/helpers.py` DSL (`create_connection`, `create_source`, etc.) via a small `docs/user/scripts/seed.py` that talks to the running API on `:8001`. Deterministic ids (`docs_demo_orders`, `docs_demo_pg`) so screenshots don't churn between captures.

Screenshots to capture (v1):
- Landing → Pipelines list (empty + populated)
- New Connection form (filesystem + s3 + postgres)
- New Source form (filesystem + sql_database)
- New Destination form (json_file)
- Pipeline Builder — sources panel, destination picker, add-step menu open
- Each step editor once
- Preview panel with sample rows
- Run detail (running, completed, failed)
- Lookup tables page

## Files to add

- `docs/user/**/*.md` (structure above)
- `docs/user/scripts/capture.ts`
- `docs/user/scripts/seed.py`
- `docs/user/assets/**/*.png` (checked in; each < ~150KB)
- `README.md` — replace the "See `./docs` (in progress)" line with a link to `docs/user/README.md`

Nothing existing is deleted or renamed.

## Reuse

- **Copy tone from** `frontend/src/components/marketing/landing-page.tsx` — sets the product voice ("map it once, run it forever"). Docs should feel like a continuation, not a switch to sterile reference.
- **Feature surface derived from** `frontend/src/components/builder/steps/types.ts` (STEP_OPS array), `backend/dte/models/pipeline.py` (ConnectionType, source/dest compat maps), `backend/dte/sources/loader.py`.
- **Screenshot seeding via** the scenario DSL in `backend/tests/scenarios/helpers.py` — do not build a parallel seeder.
- **Link into existing operator docs** at `docs/runbooks/oncall/*` for auth failures, pipelines stuck running, DuckDB OOM — no need to rewrite these for users; link them as "if something breaks".

## Out of scope for v1

- API reference (backend already exposes `/openapi.json` and `/docs` via FastAPI; link to it, don't regenerate).
- SDK docs for `packages/dte-sdk/` — separate follow-up plan.
- Publishing pipeline (Docusaurus / Next `/docs` route / search index) — do after content settles.
- Video walkthroughs.

## Verification

1. Fresh clone → follow `docs/user/getting-started/01-install.md` verbatim → stack comes up.
2. Follow `02-first-pipeline.md` step-by-step → land on a green Run detail with row count. If any step deviates from what the UI actually shows, the doc is wrong, not the app.
3. Run `node docs/user/scripts/capture.ts` on a clean docker stack → all screenshots regenerate without manual clicking; `git diff` on `assets/` shows only intentional UI changes.
4. `grep -rE "\]\(\.\./" docs/user` → every relative link resolves (spot-check with a link checker like `lychee docs/user`).
5. Manually walk each connector page against its editor at `/connections/new` and confirm the field table matches the form.
