# Plan 045 — Cloud/SaaS readiness: scheduler, usage metering, execution isolation

Covers the gaps identified when scoping a hosted flowexperts.ai Cloud tier on top of the
already-built [[030-multi-tenant-isolation]] work. Multi-tenancy (tenant model, RLS,
per-tenant secrets, JWT tenant claim) is done but shipped behind `DTE_MULTI_TENANT_ENABLED=False`.
This plan covers the three gaps that remain before that flag can be flipped on for paying
customers: **recurring runs**, **usage-based billing data**, and **execution isolation**.

Licensing (source-available terms to prevent resale-as-a-service) is a legal/business
decision, not code, and is tracked separately — not in this plan.

## Current state (verified against code)

- **Trigger model**: `POST /api/pipelines/{id}/trigger` (`dte/api/routes/pipelines.py:684-751`)
  creates a run row then does `asyncio.create_task(_task_with_context())` — pure in-process,
  no queue. `run_registry.register(run_id, task)` tracks it for cancellation only on the
  worker process that started it. Endpoint returns `{"run_id": ...}` immediately.
- **Timeout/cancel**: `_execute_pipeline` wraps `_run_body` in
  `asyncio.wait_for(..., timeout=settings.run_timeout_seconds)`
  (`dte/api/routes/pipelines.py:802-808`). `POST /runs/{id}/cancel` only works if the task is
  still alive on the same process (`run_registry.cancel`) — if the API has scaled to N
  replicas, cancel silently no-ops on N-1 of them.
- **Run model**: `rows_written`, `started_at`, `finished_at`, `status`, `error`, `location`,
  `params`, `quality_checks`, `sql_query` (spread across migrations 001-027). No elapsed-time
  or compute-cost column persisted — duration is computed via `time.monotonic()` only for a
  Prometheus histogram (`metrics.pipeline_run_duration_seconds`), never written to the row.
- **No scheduling code anywhere** — confirmed via grep, zero hits for cron/APScheduler/celery/rq
  in `dte/`.
- **Settings** (`dte/config.py:24-71`): `multi_tenant_enabled=False`, `run_timeout_seconds=1800`,
  `run_max_rows=10_000_000`. No usage/metering flags exist yet.
- Latest migration is `027_run_sql_query.py` — next is `028`.

## Gap 1 — Scheduler (recurring runs)

Cloud customers expect "run this pipeline every night at 2am," not manual-trigger-only.

### Model

New table, tenant-scoped like everything else in plan 030:

```sql
CREATE TABLE schedules (
    id text PRIMARY KEY,
    tenant_id text NOT NULL REFERENCES tenants(id),
    pipeline_id text NOT NULL REFERENCES pipelines(id),
    cron_expr text NOT NULL,           -- standard 5-field cron
    timezone text NOT NULL DEFAULT 'UTC',
    enabled boolean NOT NULL DEFAULT true,
    last_run_id text,
    next_run_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
```

`ScheduleStore` protocol in `dte/store/base.py` alongside the existing five stores:
`get`, `create`, `update`, `list_for_tenant`, `delete`. `PostgresScheduleStore` follows the
same `_open_tenant_session` pattern as `PostgresRunStore`. `FakeScheduleStore` in
`tests/fakes.py` mirrors it.

### Dispatch

A single background loop process (separate from the API — `dte/scheduler/loop.py`), not
threaded into the FastAPI app: polls `schedules` every 30s for `next_run_at <= now() AND enabled`,
calls the same trigger path the API uses (`trigger_pipeline` extracted as a callable, not just
a route handler), advances `next_run_at` via `croniter`. Runs as its own container/process in
`docker-compose.yml` and the prod deployment — this is deliberately NOT another `asyncio.create_task`
inside the API process, because a scheduler that dies with an API replica is a shipped bug, not
a feature.

Only one scheduler replica should be active — Postgres advisory lock (`pg_try_advisory_lock`)
around the poll loop gives leader election for free without adding infra.

### API

```
POST   /api/pipelines/{id}/schedules      create schedule
GET    /api/pipelines/{id}/schedules      list
PUT    /api/schedules/{id}                update cron/enabled
DELETE /api/schedules/{id}                remove
```

## Gap 2 — Usage metering

Billing (flat-tier caps and usage-based Pro pricing) needs per-tenant, per-run cost data.
Today only `rows_written` exists; nothing captures compute time per tenant or aggregates it.

### Persist duration on the run row

`_execute_pipeline` already computes elapsed via `time.monotonic()` for the Prometheus
histogram (`dte/api/routes/pipelines.py:799, 836-838`) but throws it away. Minimal fix:
write it back.

- Migration `028_run_duration_ms.py`: `ALTER TABLE runs ADD COLUMN IF NOT EXISTS duration_ms INTEGER`.
- `_execute_pipeline` includes `duration_ms` in the final `r_store.update(...)` call alongside
  `status`/`rows_written`.

### Usage aggregation table

Rather than aggregating `runs` on every billing query (expensive, and `runs` isn't partitioned
by tenant for scanning), roll up nightly:

```sql
CREATE TABLE tenant_usage_daily (
    tenant_id text NOT NULL REFERENCES tenants(id),
    day date NOT NULL,
    run_count integer NOT NULL DEFAULT 0,
    rows_processed bigint NOT NULL DEFAULT 0,
    compute_ms bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, day)
);
```

A small nightly job (same scheduler process from Gap 1, or a separate cron entry) does
`INSERT ... SELECT tenant_id, date(started_at), count(*), sum(rows_written), sum(duration_ms)
FROM runs WHERE started_at >= yesterday GROUP BY 1,2 ON CONFLICT DO UPDATE`.

### API

```
GET /api/billing/usage?from=&to=   tenant's own usage, tenant-scoped via RLS like everything else
```

This is deliberately the whole metering surface for v1 — no real-time metering, no per-run
cost breakdown UI. Billing integration (Stripe metered usage, plan enforcement) is a separate
plan once a Cloud tier actually has a paying design partner.

## Gap 3 — Execution isolation

The in-process `asyncio.create_task` model means every pipeline run on a given API replica
shares that replica's CPU/RAM. One tenant's large join/pivot can starve every other tenant's
runs on the same process, and cancel/timeout only work correctly if the run stays pinned to
the replica that started it. This is the highest-risk gap for multi-tenant Cloud — it's a
noisy-neighbor and potential DoS surface, not just a UX rough edge.

### Recommendation: external job queue, keep DuckDB in-process per worker

Do not attempt per-run containers/sandboxes for v1 — too much infra for the current scale.
Instead:

1. Introduce a job queue (Redis + `arq`, or Postgres-backed via `procrastinate` — either avoids
   adding a new datastore if Redis isn't already planned; Postgres-backed queue is the simpler
   ops story given Postgres is already the source of truth).
2. `POST /trigger` becomes: create run row (`status=pending`), enqueue job, return `run_id`
   immediately — same external contract as today.
3. A separate **worker pool** (new deployable, `dte/worker/`) pulls jobs and runs
   `_run_body` — the actual DuckDB execution logic is unchanged, only the dispatch mechanism
   moves out of the API process.
4. Per-tenant concurrency cap enforced at the queue level (e.g. `arq`'s per-queue-name
   concurrency, one logical queue per tenant tier) — this is what actually stops one tenant
   from starving others, more than the queue technology choice does.
5. `run_max_rows` / `run_timeout_seconds` (already in `config.py`) become worker-enforced
   limits instead of API-process limits — same values, different enforcement point.
6. Cancellation becomes queue-native (`arq`/`procrastinate` both support job cancellation by id)
   instead of the current best-effort `run_registry` which only works same-process.

### Non-goals for v1

- Per-run sandboxing/containers (gVisor, Firecracker) — revisit only if a customer's workload
  is adversarial, not just large.
- Autoscaling worker pool — fixed pool size, scale manually until usage data (Gap 2) justifies
  automation.

## Task list

| # | Task | Files | Branch |
|---|---|---|---|
| 1 | `ScheduleStore` protocol + Postgres + Fake impls + migration | `dte/store/base.py`, `dte/store/postgres.py`, `tests/fakes.py`, `alembic/versions/029_schedules.py` | `feature/045-1-schedule-store` |
| 2 | Scheduler loop process + advisory-lock leader election | `dte/scheduler/loop.py` (new), `docker-compose.yml` | `feature/045-2-scheduler-loop` |
| 3 | Schedule CRUD API | `dte/api/routes/schedules.py` (new) | `feature/045-3-schedule-api` |
| 4 | `duration_ms` on runs + wire into `_execute_pipeline` | `alembic/versions/028_run_duration_ms.py`, `dte/api/routes/pipelines.py` | `feature/045-4-run-duration` |
| 5 | `tenant_usage_daily` rollup + nightly job + usage API | `alembic/versions/030_tenant_usage_daily.py`, `dte/scheduler/rollup.py` (new), `dte/api/routes/billing.py` (new) | `feature/045-5-usage-metering` |
| 6 | Job queue integration (`arq` or `procrastinate`), extract `_run_body` dispatch | `dte/worker/` (new), `dte/api/routes/pipelines.py` | `feature/045-6-job-queue` |
| 7 | Per-tenant concurrency caps + queue-native cancel | `dte/worker/`, `dte/api/routes/pipelines.py` | `feature/045-7-tenant-concurrency` |

Sequencing: 1-3 (scheduler) and 4-5 (metering) are independent and can land in either order.
6-7 (execution isolation) is the largest and riskiest change — land it last, behind a flag
(`DTE_JOB_QUEUE_ENABLED`, mirroring the `DTE_MULTI_TENANT_ENABLED` rollout pattern from plan 030),
and only flip default-on after a burn-in period, same as plan 030's two-week RLS soak.

## Non-goals

- Billing/payment integration (Stripe, invoicing) — separate plan once there's a design partner.
- Per-run cost breakdown UI — v1 usage API is aggregate-only.
- Container-level execution sandboxing.
- Cross-region scheduling / DST edge cases beyond standard `croniter` behavior.
