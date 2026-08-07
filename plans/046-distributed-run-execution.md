# Plan 046 — Distributed run execution (procrastinate worker pool)

Implements Gap 3 of [[045-cloud-saas-readiness]] as a standalone plan. Pipeline runs move
out of the API process and onto a separate worker deployable, dispatched through a
Postgres-backed job queue.

Scope is **distributing runs** — N pipelines executing concurrently across a worker pool,
each still single-node DuckDB. Distributing *a single run* across a cluster is
[[034-distributed-execution-seam]] (Trino) and is orthogonal: it changes the execution
locus inside `_run_body`, this plan changes who calls `_run_body`. They compose without
conflict and can land in either order.

## Problem

Every run is an `asyncio.create_task` inside the API process
(`dte/api/routes/pipelines.py:749`). Three consequences:

1. **Noisy neighbour.** A large join/pivot consumes the same process serving HTTP. The only
   documented mitigation is vertical — raise `backend.deploy.resources.limits.memory`
   (`docs/runbooks/oncall/duckdb-oom.md:20`), which raises the ceiling for every pipeline
   and every request, not just the offender.
2. **Cancel is process-local.** `run_registry` is a module-level dict (`dte/runs.py:11`).
   Scale the API to N replicas and `POST /runs/{id}/cancel` no-ops on N-1 of them — the
   endpoint already has a "no live task on this worker" branch (`pipelines.py:775`)
   acknowledging this.
3. **The API cannot be scaled independently of execution.** Both dimensions are one knob.

## Current state (verified against code)

- **Trigger** (`pipelines.py:697-751`): resolves refs, freezes the interpolation context,
  creates the run row, spawns a task, registers it for cancel, returns `{"run_id": ...}`.
- **`_execute_pipeline`** (`pipelines.py:782-838`): status transitions, `asyncio.wait_for`
  on `settings.run_timeout_seconds`, Prometheus counters, exception → `status=failed`.
- **`_run_body`** (`pipelines.py:841+`): takes **only** `pipeline_id`, `run_id`, and eight
  store instances. No `Request`, no user object, no in-memory handoff from the trigger. It
  re-reads the frozen `params` off the run row (`pipelines.py:862`) so `now`/`today` don't
  drift. **This is already a serialisable job boundary.**
- **Stores** are async SQLAlchemy over asyncpg; `_session_factory` is an
  `@lru_cache(maxsize=1)` singleton async engine (`dte/api/deps.py:35`).
- **Tenancy**: `tenant_context_var` contextvar, set by middleware, inherited by the task
  via `copy_context()` (`pipelines.py:732`). Stores emit `SET LOCAL dte.tenant_id` per
  session (`dte/store/postgres.py:56-65`). `runs` has a `tenant_id` column
  (`alembic/versions/015_tenant_id.py:26`).
- **Output read-back**: `GET /runs/{id}/output` does `Path(location).read_text()`
  (`dte/api/routes/runs.py:76`) — the API process reads the file the executor wrote.
- Latest migration is `028_destination_type_rename.py`.
- No queue library in `backend/pyproject.toml` — no redis, celery, arq, or rq.

## Queue choice: procrastinate

**Rejected — Celery.** The execution path is async end-to-end; Celery tasks are sync
functions on a prefork pool. Bridging means `asyncio.run(_run_body(...))` per task, which
breaks concretely against the `@lru_cache` singleton engine at `deps.py:35`: the async
engine binds to the first task's event loop, then gets handed to the next task's fresh
loop, and asyncpg connections raise `Future attached to a different loop`. The workarounds
are dropping the cache (loses pooling — see [[028-connection-pooling]]) or hand-managing one
loop per worker process, which is reimplementing an async worker inside a sync one. Celery
also mandates Redis/RabbitMQ (kombu's SQLAlchemy transport is experimental and not
appropriate for a multi-tenant execution path).

**Rejected — arq.** Async-native, so it avoids the loop problem. But Redis means a second
datastore, a second backup story, a new section in `on-call.md`, and — the deciding factor
— a dual write between "run row inserted" and "job enqueued". A crash between them strands
a `pending` run nobody executes.

**Chosen — procrastinate.** Postgres-backed, asyncio-native, `LISTEN/NOTIFY` (not polling).
Three properties this design needs:

1. **Transactional enqueue.** `defer_async` inside the same transaction as the run-row
   insert. Run row exists ⟺ job exists, by construction. Removes the orphan class entirely.
2. **Tenant handoff stays inside RLS.** The job row lives in Postgres, visible to the same
   session and the same `dte.tenant_id` guard as the run row. An external broker would put
   the job payload outside the tenancy model.
3. **No new datastore.** Nothing added to `on-call.md`, `install.md` backups, or the Compose
   stateful set.

Cost: smaller community than Celery, and queue throughput is bounded by Postgres. The
second is irrelevant here — jobs are minutes-long DuckDB runs at tens per minute, against a
queue good for orders of magnitude more.

## Architecture change

```
POST /trigger ──► resolve refs, freeze params  (unchanged)
              ──► BEGIN
                    INSERT run (status=pending)
                    defer_async(execute_run, run_id, pipeline_id, tenant_id)
                  COMMIT
              ──► return {"run_id"}            (unchanged contract)

worker pod    ──► dequeue
              ──► verify payload.tenant_id == run_row.tenant_id
              ──► set tenant_context_var
              ──► _execute_pipeline(...)       (moved verbatim)
```

`_run_body` is **unchanged**. `_execute_pipeline` moves to `dte/worker/tasks.py` verbatim —
the `wait_for` timeout still applies, the enforcement point moves, the value doesn't.

### Feature flag

`DTE_JOB_QUEUE_ENABLED: bool = False` in `dte/config.py`. Off → today's `create_task` path,
untouched. Mirrors the `DTE_MULTI_TENANT_ENABLED` rollout from [[030-multi-tenant-isolation]].
This keeps the single-container Compose story working for self-hosters — the only install
path `docs/user/self-hosting/install.md` supports.

### Sharp edge 1 — local_fs is not pod-portable

`GET /runs/{id}/output` reads the output file from the API process's filesystem
(`runs.py:76`). Split execution onto another pod and that read fails for any file-shaped
destination on a `local_fs` connection.

**Decision: reject at trigger, don't fail mid-run.** When `DTE_JOB_QUEUE_ENABLED` and the
resolved destination's connection is `local_fs`, return 422 naming the constraint. `s3`,
`gcs`, and `azure` loaders/writers are already pod-agnostic and are the supported path in
distributed mode. An RWX volume (NFS/EFS) also works and stays an operator choice, so the
check is a second flag — `DTE_SHARED_OUTPUT_FS=false` by default — rather than hardcoded.

Same applies to `filesystem` **sources** on `local_fs`: the worker must be able to read the
input. Covered by the same check.

### Sharp edge 2 — tenant rehydration is security-sensitive

The contextvar mechanism does not cross a process boundary. The worker sets
`tenant_context_var` from the job payload **and cross-checks it against the run row's
`tenant_id`** before any store call. Mismatch → fail the run, log at ERROR, do not execute.
Without the cross-check a malformed or replayed job executes under another tenant's RLS
session var. This is the one genuinely security-sensitive edit in the plan and gets a
dedicated test.

### Sharp edge 3 — orphaned runs

A killed pod leaves `status=running` forever — the failure
`docs/runbooks/oncall/pipeline-stuck-running.md` already documents, more likely under k8s
eviction. Needs `runs.last_heartbeat_at`, touched every 30s by the worker, plus a reaper
that fails out runs whose heartbeat is stale by > 2× the interval. Queue-level retry does
**not** cover this: a DuckDB run is not idempotent against a destination, so automatic
re-execution could double-write. Reap to `failed`, let the user re-trigger.

### Cancel

`run_registry` (`dte/runs.py`) is replaced by procrastinate's cancel-by-job-id. The run row
gains `job_id` so the endpoint can map run → job. For an already-running job, cancellation
requests an abort; the worker's existing `asyncio.CancelledError` handler
(`pipelines.py:817`) already writes `status=failed, error="cancelled"`.

## Deployment topology

Three Deployments, two images:

| Deployment | Command | Scaling |
| --- | --- | --- |
| `dte-api` | `uvicorn dte.api.main:app` | HPA on request rate. Stateless. |
| `dte-worker` | `python -m dte.worker` | Memory-heavy. `limits.memory` maps 1:1 to a run's ceiling at concurrency 1. |
| `dte-frontend` | `next start` | Unchanged. |

Plus a Job for `alembic upgrade head` as a pre-upgrade hook. The current
migrate-then-exec-uvicorn entrypoint (`docker-compose.yml`, backend `command`) races with
N API replicas and must not be carried to k8s.

Per-tenant concurrency caps land as one logical queue per tenant tier. This — not the queue
technology — is what actually stops starvation.

Compose gains a `worker` service (same image, `command: python -m dte.worker`, same env,
`DTE_JOB_QUEUE_ENABLED=true`) so the distributed path is exercised in dev.

## Task list

| # | Task | Files | Branch |
|---|---|---|---|
| 1 | Add `procrastinate` dep; app/connector wiring reusing `DATABASE_URL`; procrastinate's own schema migration | `backend/pyproject.toml`, `dte/worker/app.py` (new), `alembic/versions/029_procrastinate.py` | `feature/046-1-queue-wiring` |
| 2 | `DTE_JOB_QUEUE_ENABLED` + `DTE_SHARED_OUTPUT_FS` settings | `dte/config.py` | `feature/046-2-flags` |
| 3 | Extract `_execute_pipeline` into `dte/worker/tasks.py`; API imports it for the flag-off path (no behaviour change, no queue yet) | `dte/worker/tasks.py` (new), `dte/api/routes/pipelines.py` | `feature/046-3-extract-executor` |
| 4 | Tenant rehydration + payload/run-row cross-check | `dte/worker/tasks.py`, `tests/unit/test_worker_tenancy.py` (new) | `feature/046-4-tenant-rehydration` |
| 5 | Flag-on trigger path: transactional enqueue, `runs.job_id` | `dte/api/routes/pipelines.py`, `dte/store/postgres.py`, `alembic/versions/030_run_job_id.py` | `feature/046-5-enqueue` |
| 6 | Worker entrypoint + Compose service | `dte/worker/__main__.py` (new), `docker-compose.yml` | `feature/046-6-worker-deployable` |
| 7 | `local_fs` guard at trigger when queue enabled and FS not shared | `dte/api/routes/pipelines.py`, `tests/scenarios/test_error_paths.py` | `feature/046-7-local-fs-guard` |
| 8 | Heartbeat column + reaper | `alembic/versions/031_run_heartbeat.py`, `dte/worker/reaper.py` (new) | `feature/046-8-heartbeat-reaper` |
| 9 | Queue-native cancel; delete `dte/runs.py` | `dte/api/routes/pipelines.py`, `dte/runs.py` (**deleted**) | `feature/046-9-distributed-cancel` |
| 10 | Docs: self-hosting scaling page, on-call runbook section | `docs/user/self-hosting/scaling.md` (new), `docs/runbooks/on-call.md` | `feature/046-10-docs` |

Sequencing: 1-3 are pure refactor and land first behind a flag that is off. 4-5 are the
functional core. 7-9 harden. 6 and 10 can land any time after 5.

Migration numbers assume 029-031 are free. [[045-cloud-saas-readiness]] task 1 also claims
029 (its "next is 028" note is stale) — whichever lands second renumbers.

## Testing

- **Unit** — tenant cross-check rejects a mismatched payload; reaper fails only stale-heartbeat
  runs; the `local_fs` guard fires only when both flags demand it.
- **Integration** — real Postgres, real procrastinate: enqueue → worker executes → run row
  reaches `completed`. Rollback of the trigger transaction leaves **no** job row.
- **Scenario** — the existing suite is the regression net. `trigger_and_wait`
  (`tests/scenarios/helpers.py`) must pass unchanged with the flag on; if the external
  contract held, the refactor held. Run the full suite in both flag states in CI.

## Non-goals

- Per-run containers/sandboxes (gVisor, Firecracker). Revisit only for adversarial workloads.
- Worker autoscaling — fixed pool until Gap 2 metering data justifies it.
- Helm chart / k8s manifests. This plan makes DTE *deployable* that way; shipping the chart
  is separate.
- Retry-on-failure. Runs are not idempotent against destinations; failed runs stay failed.
- Distributing a single run across nodes — that is [[034-distributed-execution-seam]].
