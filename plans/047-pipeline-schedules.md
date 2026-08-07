# Plan 047 — Pipeline schedules (recurring runs)

Supersedes Gap 1 of [[045-cloud-saas-readiness]]. That gap was scoped before a job queue
existed, so it proposed a standalone scheduler deployable with hand-rolled leader election.
[[046-distributed-run-execution]] introduces procrastinate, which makes most of that
machinery redundant — this plan is the rewrite.

**Depends on [[046-distributed-run-execution]] tasks 1-5.** Scheduling on top of the
`asyncio.create_task` trigger path would mean a scheduler that dies with an API replica.
Do not start this plan until triggering goes through the queue.

## Problem

Pipelines run only on manual trigger — `POST /api/pipelines/{id}/trigger`. "Run this every
night at 2am" is table stakes for anything beyond hand-driven use, and is the single most
common thing an Airflow/Prefect user expects to already exist. `ARCHITECTURE.md` lists
"Orchestrate" under non-goals, and that stands — chaining pipelines and inter-pipeline
dependencies stay out. Recurring execution of *one* pipeline does not.

## Current state (verified against code)

- No scheduling code anywhere in `dte/` — no cron, APScheduler, celery, or rq.
- `croniter` is not a dependency (`backend/pyproject.toml`).
- Trigger (`dte/api/routes/pipelines.py:697-751`) resolves source/dest/lookup refs, validates
  engine compat, resolves and freezes the interpolation context, creates the run row,
  dispatches.
- Pipelines carry **typed trigger-time params** (`Pipeline.params: list[PipelineParam]`,
  `dte/models/pipeline.py:1080`, from [[040-trigger-time-params]]). `resolve_context`
  (`dte/compiler/interpolate.py:145`) applies defaults, coerces against declared types, and
  raises `ParamValidationError` for a missing required param with no default.
- Tenant scoping is a `tenant_id` column plus RLS via `SET LOCAL dte.tenant_id`
  (`dte/store/postgres.py:56-65`).
- Store pattern: Protocol in `dte/store/base.py`, `Postgres*Store` holding a session factory,
  `Fake*Store` in `tests/fakes.py`. Ten of each today.

## Architecture: one ticker, user data in Postgres

Procrastinate's `@app.periodic` is a **code-defined** decorator evaluated at import time.
DTE's schedules are **user-defined rows** created through the API. You cannot register a
decorator per row without restarting workers on every customer edit.

So: exactly one code-defined periodic task — the ticker — which reads the user data.

```
@app.periodic(cron="* * * * *")     # the only decorator in the codebase
async def tick(timestamp):
    for s in await schedule_store.list_due(now):
        await defer(execute_run, pipeline_id=s.pipeline_id, tenant_id=s.tenant_id,
                    params=s.params, schedule_id=s.id)
        await schedule_store.advance(s.id, next_fire_after(s, now))
```

Procrastinate dedups periodic defers (uniqueness on task + period timestamp), so **only one
worker fires each tick** across the whole pool. That is the leader election plan 045 was
going to build with `pg_try_advisory_lock`.

What this deletes from plan 045's Gap 1:

| Plan 045 Gap 1 proposed | Here |
| --- | --- |
| `dte/scheduler/loop.py` as a separate deployable | A task on the existing worker pool |
| New container in Compose + prod | None |
| `pg_try_advisory_lock` leader election | Procrastinate's periodic dedup |
| 30s poll loop | `LISTEN/NOTIFY`-driven 1-minute tick |
| Extract `trigger_pipeline` into a reusable callable | Scheduler defers the same task the API defers |

That last row matters most: once triggering is "insert run row + defer job," the scheduler
and the API do the identical thing and there is nothing to extract.

Pin the procrastinate version in [[046-distributed-run-execution]] task 1 and check the
`@app.periodic` signature against the installed release — the periodic API (notably
`periodic_id`) has moved across versions.

## Model

```sql
CREATE TABLE schedules (
    id           text PRIMARY KEY,
    tenant_id    text NOT NULL,
    pipeline_id  text NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    cron_expr    text NOT NULL,              -- standard 5-field
    timezone     text NOT NULL DEFAULT 'UTC',
    params       jsonb NOT NULL DEFAULT '{}',
    enabled      boolean NOT NULL DEFAULT true,
    overlap      text NOT NULL DEFAULT 'skip',   -- 'skip' | 'allow'
    next_run_at  timestamptz,
    last_run_id  text,
    last_fired_at timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_schedules_due ON schedules (next_run_at) WHERE enabled;
```

`ScheduleBase` / `Schedule` two-class SQLModel pair in `dte/models/pipeline.py`, following
the pattern documented in `CLAUDE.md` — API-strict Literals on `Base`, plain `str` +
`sa_column` overrides on the table class.

`ScheduleStore` Protocol: `get`, `save`, `list_for_pipeline`, `list_due`, `advance`, `delete`.
`PostgresScheduleStore` uses `_open_tenant_session` like every other store;
`FakeScheduleStore` mirrors it in `tests/fakes.py`.

`ON DELETE CASCADE` on `pipeline_id`: deleting a pipeline must not leave a schedule firing
into a 404 every night.

### params validated at create time, not at 2am

A pipeline with a required param and no default fails `resolve_context` at trigger. If a
schedule doesn't carry values for those, it fails silently every night and the user finds
out from an empty destination. So `POST /schedules` runs `resolve_context(pipeline, params)`
and returns 422 on `ParamValidationError` — the same validation the trigger route already
does, moved earlier.

`{{now}}` / `{{today}}` still resolve **at fire time**, not at schedule-create time. Only
user-supplied param values are stored.

## Semantics worth deciding now

**Missed ticks do not backfill.** If the worker pool is down from 01:00 to 07:00, a 2am
schedule fires **once** at 07:00 (or not at all — see below), never six times. `advance()`
computes the next fire strictly after `now`, discarding intermediate periods. Backfill is a
correctness trap for non-idempotent destinations and an ambush for anyone whose pipeline
truncates before writing.

**Grace period.** A tick that is due but more than `DTE_SCHEDULE_GRACE_SECONDS` (default 900)
late is skipped rather than fired, and logged at WARN. Firing a 2am nightly job at 11am is
usually worse than not firing it.

**Overlap: skip by default.** If the schedule's previous run is still `pending`/`running`,
the default `overlap='skip'` records a skip and advances. A nightly job that starts taking
25 hours must not stack up N concurrent DuckDB runs and take the worker pool down. `'allow'`
is available for users who know their pipeline is safe to run concurrently.

**Timezone and DST.** `croniter` with a `zoneinfo` tz. Spring-forward: a 02:30 schedule on
the skipped hour fires once at 03:00. Fall-back: fires on the **first** occurrence of the
repeated hour, not both. Both cases get an explicit unit test — this is where cron
implementations quietly disagree.

## API

```
POST   /api/pipelines/{id}/schedules      create (422 on bad cron or bad params)
GET    /api/pipelines/{id}/schedules      list for pipeline
GET    /api/schedules/{id}                get
PUT    /api/schedules/{id}                update cron / tz / params / enabled / overlap
DELETE /api/schedules/{id}                remove
```

Permissions reuse the existing ladder: `pipeline:read` to list, `pipeline:trigger` to
create/update/delete — scheduling is triggering on a timer, not a new authority.

Runs created by a schedule carry `schedule_id` on the run row so the UI can distinguish
"ran because a human clicked" from "ran because it was 2am".

## Task list

| # | Task | Files | Branch |
|---|---|---|---|
| 1 | `croniter` dep; `next_fire_after()` helper with tz + DST handling | `backend/pyproject.toml`, `dte/scheduling/cron.py` (new), `tests/unit/test_cron.py` (new) | `feature/047-1-cron-helper` |
| 2 | `ScheduleBase`/`Schedule` models + `ScheduleStore` protocol + Postgres + Fake impls + migration | `dte/models/pipeline.py`, `dte/store/base.py`, `dte/store/postgres.py`, `tests/fakes.py`, `alembic/versions/032_schedules.py` | `feature/047-2-schedule-store` |
| 3 | Schedule CRUD API with create-time cron + param validation | `dte/api/routes/schedules.py` (new), `dte/api/main.py` | `feature/047-3-schedule-api` |
| 4 | `runs.schedule_id` column + threaded through the defer path | `alembic/versions/033_run_schedule_id.py`, `dte/worker/tasks.py` | `feature/047-4-run-provenance` |
| 5 | Ticker periodic task: due query, overlap skip, grace period, advance | `dte/worker/scheduler.py` (new) | `feature/047-5-ticker` |
| 6 | `DTE_SCHEDULES_ENABLED`, `DTE_SCHEDULE_GRACE_SECONDS` settings | `dte/config.py` | `feature/047-6-flags` |
| 7 | Frontend: schedule list + cron editor on pipeline detail | `frontend/src/components/builder/schedules/` (new), `frontend/src/lib/api.ts` | `feature/047-7-ui` |
| 8 | Docs: user-facing scheduling page + on-call section for stuck/skipped schedules | `docs/user/pipelines/scheduling.md` (new), `docs/runbooks/on-call.md` | `feature/047-8-docs` |

Sequencing: 1-2 are independent and land first. 5 needs 2 and 4. 7 needs 3.

Migration numbers assume [[046-distributed-run-execution]] has taken 029-031.

## Testing

- **Unit** — `next_fire_after` across both DST transitions; missed-tick collapse (down 6h →
  one fire, not six); grace-period skip; overlap skip when prior run is `running`; param
  validation rejects a schedule missing a required param.
- **Integration** — real Postgres: `list_due` respects tenant RLS; `advance` is atomic under
  two concurrent tickers (belt-and-braces on top of procrastinate's dedup — the invariant
  is one run per schedule per period, and it should hold even if the dedup is bypassed).
- **Scenario** — create schedule → force a tick → run reaches `completed` with `schedule_id`
  set. Add to `tests/scenarios/`, matching the async fixture conventions.

## Non-goals

- **Pipeline chaining / DAGs.** "Run B after A succeeds" is orchestration, which
  `ARCHITECTURE.md` explicitly excludes. Users who need it point Airflow at the trigger API.
- **Sub-minute schedules.** The tick is 1 minute; that is the floor. Anything finer wants a
  streaming model, which is a P4 concern.
- **Backfill / catch-up runs.** Deliberately excluded above.
- **Per-schedule alerting on failure.** Notification routing is its own plan; failed
  scheduled runs surface through the same run history and metrics as manual ones.
- **Calendar/interval expressions beyond 5-field cron** (`@every 90m`, business-day rules).
