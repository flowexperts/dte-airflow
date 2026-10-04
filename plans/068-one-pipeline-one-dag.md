# Plan 068 — One pipeline, one schedule, one DAG

## Problem
A pipeline becomes `1 + N` DAGs: a manual `dte__<pipeline>` plus a
`dte__<pipeline>__<schedule>` for each enabled schedule (`dte/airflow/dag_factory.py`).
So one pipeline's run history is split across several DAGs. Cancel has to rebuild the
DAG id from `run.schedule_id` (`routes/pipelines.py:1162`), and the runs view parses the
schedule id out of `dag_id` (`store/postgres.py:64`).

There is a second problem. An Airflow DAG version does not correspond to a pipeline
version:
- The DAG is built only from id, name and type. Editing a pipeline's steps does not
  change the serialized DAG, so Airflow does not create a new DagVersion.
- The operator runs the **live** `pipelines` row (`operators.py:79`). `revision_id` is
  recorded but never executed, so a run pinned to revision 3 actually runs whatever is
  saved when the task starts.

## Decision
- **One pipeline has at most one schedule, and one DAG: `dte__<pipeline_id>`.**
- **The schedule is part of the pipeline spec**: a `schedule` field on `PipelineBase`,
  stored as JSONB. Changing the schedule is a pipeline save, which records a revision.
- **Pipeline revision = DAG version.** The DAG factory passes the pipeline's latest
  `revision_id` to `DtePipelineOperator`. Every save therefore changes the serialized DAG,
  and Airflow creates a new DagVersion. The operator executes `PipelineRevision.config`
  for that revision, not the live row, so each run in Airflow's history is the exact
  spec that ran.

```
save pipeline ─▶ pipeline_revisions row (config incl. schedule)
                        │ dag-processor parse
                        ▼
dte__<pipeline>  schedule=cron|None  params=schedule.params
  └─ DtePipelineOperator(revision_id=<latest>)  ─▶ new DagVersion per revision
        run ─▶ loads PipelineRevision.config, runs that
```

### Consequences, accepted
- Manual and scheduled runs share one DAG, so they share `max_active_runs`. With
  `overlap="skip"`, a manual trigger waits in the queue behind a running scheduled run.
  It is queued, not dropped.
- Manual runs use DAG params as defaults. Explicit `conf.params` still wins (the operator
  already handles this).
- Pipelines with several schedules today: the migration keeps the **most recently
  updated enabled** schedule, or the most recent one if none are enabled, and drops the
  rest. The dropped schedules are logged by the migration.
- A pipeline with no revision yet (created before revisions existed) gets one written
  by the migration, so every DAG has a `revision_id`.

## Model
```python
class PipelineSchedule(SQLModel):          # embedded, not a table
    cron_expr: str
    timezone: str = "UTC"
    params: dict[str, str] = {}
    enabled: bool = True
    overlap: OverlapPolicy = "skip"
    eval_set_id: str | None = None

PipelineBase.schedule: PipelineSchedule | None = None   # JSONB column on pipelines
```
The `Schedule` table, `ScheduleStore`, and `runs.schedule_id` are deleted.

## API
- `GET/PUT/DELETE /api/pipelines/{id}/schedule` (`routes/schedules.py`, rewritten): each
  change saves the pipeline and records a revision. `pipeline:trigger` is needed to write.
- The pipeline POST/PUT also accept `schedule` and run the same `validate_schedule`. A PUT
  that **omits** `schedule` keeps the current one, so the builder can't wipe it. The
  frontend's `updatePipeline` always omits it, because its copy may be older than an edit
  made in the panel.
- Deleting an eval set: the 409 check scans `pipelines.schedule.eval_set_id`.
- Runs: `schedule_id` is replaced by `scheduled` (`dag_run.run_type = 'scheduled'`).

## As built: how the revision reaches the DAG
Airflow does not serialize custom operator attributes, and the worker re-parses the DAG
file at execution time. So `revision_id` on the operator alone would neither create a new
DagVersion nor pin anything. Instead:
- The DAG gets the tag `dte-revision:<id>`. Tags are serialized, so each revision changes
  the DAG. Airflow 3 starts a new DagVersion once the previous version has runs; until
  then it updates that version in place.
- Manual and sweep runs pin `conf.revision_id`. `trigger_dag_run` waits until the DAG
  carries that tag, so the run is filed under the matching DagVersion.
- Scheduled runs use the operator's `revision_id`, which is the latest at parse time.
- Every save path records a revision: builder, schedule, as-eval, promote and sweep
  variants.

## Tasks (branch `feature/068-one-pipeline-one-dag`)
1. **Tests first**:
   - `dag_factory` builds exactly one DAG per pipeline, and it has the cron when a
     schedule is set and enabled.
   - The DAG's operator carries the latest `revision_id`.
   - The operator runs the revision's config, not the live row. Test: edit the row
     after the revision and check the old config runs.
   - The pipeline PUT validates the schedule. Port the cases from
     `test_api_schedules*.py`.
   - Eval set delete gets a 409 when a pipeline's schedule references the set.
2. **Model and migration `040_pipeline_schedule.py`**: add `pipelines.schedule` JSONB,
   backfill it from `schedules` using the rule above, backfill missing revisions (their
   config includes `schedule`), then drop `schedules` and `runs.schedule_id`.
3. **DAG factory**: one loop and one DAG per pipeline, with `revision_id` taken from the
   latest revision.
4. **Operator**: load `PipelineRevision.config` into `Pipeline` for `self.revision_id`,
   and fail if the revision is missing. `eval_set_id` comes from conf, then from the
   schedule in the revision config.
5. **API**: put the schedule validation into the pipeline routes. Delete
   `routes/schedules.py`, the schedule store and the schedule deps. Remove the
   `schedule_id` suffix from `cancel_run`. Remove `schedule_id` from `_RUNS_SQL`.
6. **Frontend**: `SchedulePanel` edits one schedule and saves it through the pipeline
   PUT. Drop the list/add UI and the `/api/schedules` calls in `lib/api.ts`. Regen types.
7. **Docs**: `ARCHITECTURE.md` DAG factory line, `backend/dte/api/CLAUDE.md`,
   `backend/dte/evals/CLAUDE.md`.

## Files
Changed: `dte/models/pipeline.py`, `dte/airflow/dag_factory.py`,
`dte/airflow/operators.py`, `dte/api/routes/pipelines.py`, `dte/api/routes/evals.py`,
`dte/api/main.py`, `dte/api/deps.py`, `dte/store/base.py`, `dte/store/postgres.py`,
`tests/fakes.py`, `tests/conftest.py`, `frontend/src/lib/api.ts`,
`frontend/src/components/builder/schedules/*`, `frontend/src/components/pipeline/canvas.tsx`,
docs above.
New: `alembic/versions/040_pipeline_schedule.py`.
Deleted: `dte/api/routes/schedules.py`, `tests/unit/test_api_schedules.py`,
`tests/unit/test_api_schedules_eval.py` (cases ported), `tests/unit/test_schedule_store.py`,
`tests/unit/test_schedule_model.py`.
