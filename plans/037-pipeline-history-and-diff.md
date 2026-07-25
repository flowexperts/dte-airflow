# Plan 037 — Pipeline history + diff view

Closes P4 #43 from `plans/027-p0-p4-status-ladder.md`. Sequenced 1st in `plans/035-p4-differentiator-roadmap.md` — smallest scope, highest immediate customer value ("why did this pipeline start behaving differently?").

## Problem

Every pipeline edit clobbers the previous version. Once a run starts misbehaving after a change, there is no answer to:

- What did this pipeline look like on 2026-06-01?
- Who changed the join key on the `orders → customers` step?
- Which revision was this run compiled against?

Support has to reconstruct history from Postgres WAL or user memory. Both fail.

## Scope

**In:**
- Persist every accepted `POST /api/pipelines` and `PUT /api/pipelines/{id}` body as an immutable revision row.
- Pin each `Run` to the revision id used to trigger it.
- API: `GET /api/pipelines/{id}/revisions` (list), `GET /api/pipelines/{id}/revisions/{rev_id}` (fetch), `GET /api/pipelines/{id}/diff?from=<rev>&to=<rev>` (server-side diff — returns a structured JSON diff, not a text patch).
- Frontend: **History** tab on the pipeline detail page. List of revisions (author, timestamp, one-line summary of changed keys); click a pair to see side-by-side JSON diff. Run detail page shows "compiled from revision `abc123` — [view]".

**Out:**
- Branching / merging (linear history only — non-goal called out in plan 035).
- Restoring a revision as the current version (add later as one endpoint if customers ask; MVP is read-only).
- Diffing sources / destinations / connections. Pipelines only. (These entities do change less often; extension is straightforward once the pattern is set.)
- Retention policy — write everything for now. Cost mitigation (keep last 100 + monthly) is a follow-up when a customer hits the storage floor.

## Data model

New table `pipeline_revisions` (alembic `014_pipeline_revisions.py`):

```sql
CREATE TABLE pipeline_revisions (
  id           TEXT PRIMARY KEY,           -- ulid or short hash
  pipeline_id  TEXT NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
  config       JSONB NOT NULL,             -- full PipelineBase.model_dump()
  changed_by   TEXT,                       -- users.id, nullable (system writes)
  changed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  summary      TEXT                        -- one-line: "steps: +filter, -sort; name changed"
);
CREATE INDEX ix_pipeline_revisions_pipeline_changed
  ON pipeline_revisions (pipeline_id, changed_at DESC);
```

`runs` gains `revision_id TEXT NULL REFERENCES pipeline_revisions(id)` — same migration. Existing rows stay NULL; not backfilled (they predate revision tracking).

## Backend changes

- `dte/models/pipeline.py` — add `PipelineRevisionBase` / `PipelineRevision` two-class SQLModel pair. `Run` gains `revision_id: str | None`.
- `dte/store/base.py` — `PipelineRevisionStore` protocol: `save(rev)`, `get(rev_id)`, `list(pipeline_id, limit)`. `PipelineStore.save` grows an optional `changed_by` and internally records a revision after committing the pipeline row.
- `dte/store/postgres.py` — `PostgresPipelineRevisionStore`; `PostgresPipelineStore.save` writes both rows in one transaction. `PostgresRunStore.create` accepts a `revision_id`.
- `tests/fakes.py` — `FakePipelineRevisionStore`; matching hook in `FakePipelineStore.save`.
- `dte/api/routes/pipelines.py` — new routes:
  - `GET /api/pipelines/{id}/revisions?limit=100`
  - `GET /api/pipelines/{id}/revisions/{rev_id}`
  - `GET /api/pipelines/{id}/diff?from=&to=` — reuses `_diff_pipeline` helper.
- `dte/api/routes/pipelines.py::trigger_pipeline` — resolves current revision, passes `revision_id` to `RunStore.create`.
- `dte/pipelines/diff.py` — new module. `diff_pipeline(a: dict, b: dict) -> PipelineDiff` returns `{name, sources_added, sources_removed, steps: [{index, op, kind: added|removed|changed, before, after}], output_id_changed}`. Deterministic, JSON-serialisable. Diff at step granularity, not per-key inside a step — steps are already small.
- `_summarise_diff(diff) -> str` — writes the `summary` column.

## Frontend changes

- `src/lib/api.ts` — `listPipelineRevisions`, `getPipelineRevision`, `diffPipelineRevisions`, plus generated types.
- `src/app/(app)/pipelines/[id]/page.tsx` — add tab bar: **Overview | History**. History tab is a client component (`components/builder/history/HistoryPanel.tsx`).
- `components/builder/history/HistoryPanel.tsx` — list of revisions (`Panel` + `Item`), select up to two, render `<DiffView>` below.
- `components/builder/history/DiffView.tsx` — two-column list of changed steps + name/sources/output changes. Uses existing `ExprCode` / `KV` primitives; no external diff lib for MVP (JSON step comparisons are small).
- `src/app/(app)/runs/[id]/page.tsx` — under `MetricRow`, show "revision `<short>` [view]" linking to `/pipelines/{id}?rev=<id>`.

## Task list (branches)

Every branch is a worktree per project convention.

1. `feature/history-model` — migration `014`, SQLModel + store protocol + fakes + Postgres store. Unit tests for the store (memory + postgres integration) and a scenario test that: create pipeline → PUT 3 times → assert 4 revisions and every field diff. Wire `Run.revision_id` on trigger.
2. `feature/history-api` — the three GET routes + `dte/pipelines/diff.py` + unit tests for the diff helper (deterministic snapshot fixtures). Scenario test hits `/diff?from=&to=` end-to-end.
3. `feature/history-ui` — History tab, DiffView, run-detail revision line. Wire generated types (`pnpm gen:types` after branch 2 lands).

Each branch merges to `main` with `--no-ff`. Update `plans/027` row #43 to ✅ after branch 3 lands.

## Files changed / added

**Added:**
- `backend/alembic/versions/014_pipeline_revisions.py`
- `backend/dte/pipelines/diff.py`
- `backend/tests/unit/test_pipeline_diff.py`
- `backend/tests/scenarios/test_pipeline_history.py`
- `frontend/src/components/builder/history/HistoryPanel.tsx`
- `frontend/src/components/builder/history/DiffView.tsx`

**Modified:**
- `backend/dte/models/pipeline.py` (add revision model, `Run.revision_id`)
- `backend/dte/store/{base,postgres}.py` (new store, revision hook on save)
- `backend/tests/fakes.py`
- `backend/dte/api/routes/pipelines.py` (routes + trigger wiring)
- `frontend/src/lib/api.ts`, `frontend/src/lib/api-types.ts` (regen)
- `frontend/src/app/(app)/pipelines/[id]/page.tsx`
- `frontend/src/app/(app)/runs/[id]/page.tsx`
- `plans/027-p0-p4-status-ladder.md` (row #43 → ✅ + link here)

## Non-goals (repeated for the reader who skipped)

- Branching, merging, revert.
- Diffs on sources / destinations / connections.
- Retention pruning.
- Interactive per-key JSON diff inside a single step (whole-step diff is enough for MVP).

## Success criteria

- Every accepted `POST/PUT /api/pipelines*` writes exactly one revision row.
- Every triggered `Run` has a non-null `revision_id`.
- `GET /api/pipelines/{id}/diff?from=r1&to=r2` returns a deterministic structured diff (snapshot-tested).
- History tab renders a two-revision diff for a pipeline that has been edited at least twice.
- `plans/027` #43 flips to ✅.
