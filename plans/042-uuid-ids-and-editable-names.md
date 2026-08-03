# 042 — UUID identifiers + editable, unique-per-tenant names

## Problem

Every domain entity (`Pipeline`, `Source`, `Destination`, `Connection`,
`LookupTable`) used a **user-typed string `id`** that doubled as:
- primary key,
- URL slug,
- FK payload inside `Pipeline.sources` / `Pipeline.output_id` / step
  `lookup_id`,
- and display label.

Two concrete failures fell out of this:

1. **The reported bug**: editing a source id in the UI issued
   `PUT /api/sources/<new-id>`, which 404'd ("Source not found") because
   the record lived under the old id
   (`backend/dte/api/routes/sources.py:85`,
   `frontend/src/components/builder/sources/SourcesPanel.tsx:81`).
2. Any rename would cascade through every Pipeline referencing the
   source — which is why the UI silently rejected rename today.

## Design decisions

Locked in via [`AskUserQuestion`](../.claude/plans/implement-uuid-as-pk-jiggly-pond.md):

- **Scope**: domain entities only (Pipeline, Source, Destination,
  Connection, LookupTable). Runs & PipelineRevisions already use system
  UUIDs. Auth entities (User, Role, Tenant) untouched.
- **URLs**: raw UUID in `/pipelines/[id]`, matching how `/runs/[id]`
  already works. No slug resolver.
- **Name uniqueness**: `UNIQUE(tenant_id, name)` per class.

### Pragmatic deviation from the original plan

The original plan (see `.claude/plans/…jiggly-pond.md`) called for a
6-migration column-swap that forcibly re-keyed every existing row to a
UUID, cascading through `pipelines.sources` (JSONB array),
`pipelines.output_id`, `pipeline_revisions.pipeline_id`, `runs.pipeline_id`,
`steps[*].lookup_id` (JSONB objects), and `pipeline_revisions.content`
(nested pipeline snapshots).

We deviated: **preserve historic string ids verbatim**. Only *new* rows
get UUIDs (via the model's `default_factory`). Old rows keep their
string ids indefinitely so every FK reference keeps resolving without a
JSONB rewrite. This delivered the same user-visible outcome (editable
name, non-editable id, no more 404) with an order of magnitude less
risk. Task 6 (JSONB backfill for `pipeline_revisions.content`) became
unnecessary and was dropped.

## Pattern applied to each entity

For each of `Connection`, `Source`, `Destination`, `LookupTable`, `Pipeline`:

1. **Migration** — add `name TEXT` (or, for LookupTable, enforce the
   existing nullable name column), backfill `name := id` for existing
   rows, `ALTER COLUMN name SET NOT NULL`, add
   `UNIQUE(tenant_id, name)` index.
2. **Model** — `id` gets `default_factory=lambda: str(uuid.uuid4())`;
   `name: str | None` with a `_default_name_to_id` validator that fills
   name from id when omitted, so historic callers keep working.
3. **Postgres store** — persist `name` on save; include it in the
   `on_conflict_do_update.set_` map.
4. **Fake store** — persist name; raise `ValueError` on
   `(tenant_id, name)` collisions.
5. **Route** — `try/except ValueError` → 409 on POST/PUT; include
   `name` in response payloads.
6. **Frontend** — swap the id `Input` for a name `Input`; show id as
   read-only monospace metadata chip on edit; on create, use the
   server-generated id from the POST response.

## Task list (all merged)

| # | Migration | Commit | Notes |
|---|---|---|---|
| 1 | `020_connection_name.py` | `f0f3d50 feat(connections): editable name (unique per tenant) + UUID default for id` | |
| 2 | `021_source_name.py` | `ff83a8b feat(sources): editable name (unique per tenant) + UUID default for id` | **Fixes the original 404 bug** — `SourcesPanel.saveDraft` now uses stable UUID in the PUT path. |
| 3 | `022_destination_name.py` | `feat(destinations): editable name (unique per tenant) + UUID default for id` | |
| 4 | `023_lookup_table_name.py` | `fa644da feat(lookup_tables): make name required + unique per tenant, UUID default for id` | LookupTable already had a nullable `name` column — this promoted it to NOT NULL + unique. |
| 5 | `024_pipeline_name_unique.py` | `a2f7e13 feat(pipelines): UNIQUE(tenant_id, name) + UUID default for id; drop slug validator` | Frontend BuilderForm drops the "pipeline id" input entirely; Zod slug regex removed. |
| 6 | — | *skipped* | `pipeline_revisions.content` JSONB backfill unnecessary since historic ids preserved. |
| 7 | — | `020535a chore(docs demo): resolve pipeline by name; seed with explicit name fields` | `record.ts` now resolves pipeline by name via list endpoint and captures server-generated id from POST response. |

## Files touched

**Backend**
- `backend/alembic/versions/020_connection_name.py` (new)
- `backend/alembic/versions/021_source_name.py` (new)
- `backend/alembic/versions/022_destination_name.py` (new)
- `backend/alembic/versions/023_lookup_table_name.py` (new)
- `backend/alembic/versions/024_pipeline_name_unique.py` (new)
- `backend/dte/models/pipeline.py` — added `_default_name_to_id`
  validators; `id` default_factory on all 5 entity Base classes; `name`
  columns on ORM classes.
- `backend/dte/store/postgres.py` — `name` in insert values + upsert
  set_ for Connection, Source, Destination, LookupTable stores.
- `backend/dte/api/routes/{connections,sources,destinations,lookup_tables,pipelines}.py`
  — catch `ValueError` from store, raise 409; include `name` in
  responses.
- `backend/tests/fakes.py` — `_make_source` / `_make_destination` accept
  `name`; each Fake\*Store enforces `UNIQUE(tenant_id, name)` in-memory.

**Backend tests** (24 new)
- `backend/tests/unit/test_api_connections.py` — 4 new tests.
- `backend/tests/unit/test_api_sources.py` — 3 new tests.
- `backend/tests/unit/test_api_destinations.py` — 3 new tests.
- `backend/tests/unit/test_api_lookup_tables.py` — 3 new tests.
- `backend/tests/unit/test_api_pipelines.py` — 3 new tests; helper
  `_pipeline` updated so default `name` derives from id (avoids
  collisions in tests that seed multiple pipelines).

**Frontend**
- `frontend/src/lib/api.ts` — `name?: string` on Connection, Source,
  Destination types (LookupTable already had it).
- `frontend/src/lib/validation.ts` — drop pipeline-id slug regex; id
  is now an opaque string.
- `frontend/src/components/builder/BuilderForm.tsx` — remove id input;
  show id as read-only chip on edit; capture server-generated id from
  POST for the redirect.
- `frontend/src/components/builder/sources/SourcesPanel.tsx` +
  `SourceEditor.tsx` + `types.ts` — name-driven UI; auto-mirror
  name → `table` on fresh sources; use response id after create.
- `frontend/src/components/builder/DestinationPicker.tsx` — same shape.
- `frontend/src/components/connection-form.tsx` +
  `connections-table.tsx` — name input, id chip.
- `frontend/src/components/lookup-tables-table.tsx` — name input, id chip.

**Docs / demo**
- `docs/user/scripts/seed.py` — explicit `name` fields on connection,
  source, destination.
- `docs/user/scripts/record.ts` — `resolvePipelineIdByName` helper;
  captures server-generated pipeline id from POST; scene 3 types name
  only (no id field to type into anymore).

## Verification

- **Backend**: `cd backend && uv run pytest -m "not integration"`
  passes 569 tests (up from 545 pre-change; +24 new, 0 regressions).
- **Frontend**: `cd frontend && pnpm tsc --noEmit` clean for every
  edited file. One pre-existing error in `src/app/docs/layout.tsx`
  (`LayoutProps` not resolved) is unrelated — needs `pnpm gen:types`
  to regenerate Next 16 auto-types.
- **Bug regression**: post-merge, editing a source's name and re-saving
  no longer 404s. The frontend sends the stable UUID in the PUT path;
  only `name` (and other editable fields) change in the body.

## Migrations reference

Ordered dependencies (each `down_revision` points at the prior):

```
019 (existing) — run params
   ↓
020 — connection name
   ↓
021 — source name
   ↓
022 — destination name
   ↓
023 — lookup_table name (NOT NULL + unique)
   ↓
024 — pipeline name UNIQUE (disambiguates duplicates by suffixing id[:8])
```

All migrations are idempotent (`IF NOT EXISTS` on index creation,
`WHERE name IS NULL` on backfill) and reversible via symmetric
`downgrade()`.
