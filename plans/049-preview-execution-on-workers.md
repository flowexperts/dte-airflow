# Plan 049 — Move preview and dry-run execution to workers

Depends on [[046-distributed-run-execution]] tasks 1–5 — reuses the procrastinate app,
worker deployable, and store wiring introduced there.

## Context

[[046-distributed-run-execution]] moved *runs* out of the API process but left every
interactive execution path in it. Preview and dry-run still compile and execute DuckDB inside
the FastAPI process, so the noisy-neighbour problem 046 set out to fix is only half solved.

Two things make this worse than it looks, both measured against the `dte047` stack on a
10M-row / 1.1 GB JSONL source (`load_test_10m`: filter + aggregate → 5 rows):

1. **`limit` bounds output rows, not work.** `?limit=100` on that pipeline scans all 10M rows
   to emit 5. Blocking operators (aggregate, sort, join) cannot be short-circuited by a
   downstream LIMIT. Peak API memory rose 231 MB → 336 MB for a "100-row" preview.
2. **The execution is synchronous inside `async def`, so it blocks the event loop.**
   `/healthz` normally answers in ~5 ms; during that 1.6 s preview one probe took **1380 ms**.
   The whole API replica stalls for the duration of any preview.

The intended outcome: preview and dry-run execute on workers, on their own queue, so the API
process serves HTTP and nothing else — while the HTTP contract callers already depend on
stays unchanged.

### A latent bug this must fix on the way

`_heartbeat_loop` (`backend/dte/worker/tasks.py:230`) runs as an asyncio task in the **same
event loop** as `_execute_pipeline`, which calls blocking DuckDB. `REAP_THRESHOLD_SECONDS` is
60 (`dte/worker/reaper.py:28`). So any run whose DuckDB call blocks for more than 60 s starves
its own heartbeat and `reap_stale_runs` fails a **healthy, still-executing run**. Tests miss
it because their fixtures finish in milliseconds. Moving interactive previews onto workers
makes that loop busier, so the offload fix is a prerequisite, not a nice-to-have.

## Current state (verified against code)

Four routes in `backend/dte/api/routes/pipelines.py` touch DuckDB in-process:

| Route | Line | Executes? |
| --- | --- | --- |
| `GET /pipelines/{id}/preview` | 679 | yes — `compiled.limit(limit).execute()` |
| `POST /pipelines/dry-run` | 611 | yes — unsaved pipeline in body |
| `POST /pipelines/step-schemas` | 574 | compiles only, but `load_source` still does source I/O |
| `_compile_body_pipeline` (shared helper) | 523 | builds `DuckDBEngine()` + `load_source` |

- `DuckDBEngine.__init__` (`dte/engine/duckdb_engine.py:30`) calls `ibis.duckdb.connect()`
  with **no** `memory_limit` or thread config.
- **No** `run_in_threadpool` / `asyncio.to_thread` / `run_in_executor` anywhere in
  `dte/api/routes/pipelines.py` or `dte/worker/tasks.py`.
- Preview returns rows in the response body: `{rows, count, step_sqls, final_sql, error}`.
- The trigger path's `local_fs` guard (`_check_shared_fs_guard`) is **not** applied to preview.
- Latest migrations: 046 took 029–031, 047 took 032–033. Next free is **034**.

## Architecture change

```
GET /preview  ─► resolve refs, guard local_fs
              ─► INSERT preview_results (status=pending)
              ─► defer execute_preview on the `preview` queue
              ─► await completion up to DTE_PREVIEW_WAIT_SECONDS
              ─► return {rows, count, step_sqls, final_sql, error}   ← unchanged body

preview worker ─► asyncio.to_thread(compile + execute)
               ─► UPDATE preview_results (rows | error)
```

### Decisions

**Separate `preview` queue, not a separate queue system.** Previews are latency-sensitive and
short; runs are long. On one queue a preview waits behind a 40-minute run — head-of-line
blocking. procrastinate supports named queues, so this costs a worker deployment, not new
infra.

**The HTTP contract does not change.** The API enqueues and then waits for the result, so
callers and the frontend see exactly the response they see today. procrastinate uses
`LISTEN/NOTIFY`, so pickup is milliseconds, not poll-interval. Exceeding
`DTE_PREVIEW_WAIT_SECONDS` (default 30) returns **202** with `{preview_id}` and the caller
polls `GET /previews/{id}` — a new endpoint, additive only.

**All DuckDB work moves to a thread** via `asyncio.to_thread`, in both the preview task and
`_execute_pipeline`. This is unconditional and independent of any flag: it is what stops the
event loop stalling and what stops the reaper killing healthy runs.

**Flagged rollout.** `DTE_PREVIEW_QUEUE_ENABLED`, default `False`, mirroring
`DTE_JOB_QUEUE_ENABLED`. Off → today's in-process path (now thread-offloaded). The scenario
suite must pass in both states.

**Results are transient.** `preview_results` rows carry a TTL; a cleanup pass in the existing
reaper loop deletes rows older than `DTE_PREVIEW_TTL_SECONDS` (default 3600). Preview output
is capped at `limit` rows, so the jsonb payload stays small.

**`local_fs` guard extends to preview.** Same reasoning as 046's sharp edge — a preview worker
on a different pod can't read the API pod's local files. Reuse `_check_shared_fs_guard`
(`dte/api/routes/pipelines.py`, used by `trigger_pipeline`) rather than writing a second one.

`step-schemas` stays in-process for now: it compiles without executing, and its latency budget
is a keystroke. It still does source I/O, so it inherits the thread offload from task 1 but not
the queue.

## Task list

| # | Task | Files | Branch |
|---|---|---|---|
| 1 | Offload blocking DuckDB to threads in `_execute_pipeline` + preview routes; regression test that a >60 s blocking run keeps heart-beating | `dte/worker/tasks.py`, `dte/api/routes/pipelines.py`, `tests/unit/test_worker_heartbeat.py` | `feature/049-1-thread-offload` |
| 2 | `PreviewResult` model + `PreviewResultStore` (Postgres + Fake) + migration `034_preview_results.py` | `dte/models/pipeline.py`, `dte/store/{base,postgres}.py`, `tests/fakes.py`, `alembic/versions/034_preview_results.py` | `feature/049-2-preview-store` |
| 3 | `execute_preview` task on the `preview` queue; extract the compile+execute body out of the routes so both paths share it | `dte/worker/preview.py` (new), `dte/api/routes/pipelines.py` | `feature/049-3-preview-task` |
| 4 | API dispatch: enqueue + bounded wait + 202 fallback; `GET /previews/{id}`; `DTE_PREVIEW_QUEUE_ENABLED` / `DTE_PREVIEW_WAIT_SECONDS` | `dte/api/routes/pipelines.py`, `dte/config.py` | `feature/049-4-api-dispatch` |
| 5 | Preview worker deployable (`--queues preview`) + compose service with its own memory limit | `dte/worker/__main__.py`, `docker-compose.yml` | `feature/049-5-preview-worker` |
| 6 | `local_fs` guard on preview + `preview_results` TTL cleanup in the reaper loop | `dte/api/routes/pipelines.py`, `dte/worker/reaper.py`, `dte/config.py` | `feature/049-6-guards-cleanup` |
| 7 | Docs: scaling page gains a preview section; on-call gains preview-queue triage | `docs/user/self-hosting/scaling.md`, `docs/runbooks/on-call.md` | `feature/049-7-docs` |

Task 1 is independent and should land first — it fixes a shipped bug on its own. 2–4 are the
core. 5–6 harden.

## Verification

**Unit.** Thread offload returns identical results to the direct call. A simulated 90 s
blocking execute still heartbeats (the current code fails this). The `local_fs` guard fires on
preview only when the queue is on and the FS isn't shared.

**Integration** (real Postgres, one file at a time — a shared throwaway container corrupted
results during 046):
- enqueue a preview → preview worker executes → `preview_results` reaches `completed` with rows
- a rolled-back request leaves no orphan `preview_results` row
- TTL cleanup deletes expired rows and leaves live ones

**Scenario** — the regression net. `tests/scenarios/steps/test_preview_endpoint.py` must return
byte-identical bodies with `DTE_PREVIEW_QUEUE_ENABLED` on and off. Note
`test_preview_returns_422_on_compile_error` is a **known pre-existing failure on `main`** —
do not try to fix it here.

**End-to-end**, against the `dte047` stack already running (frontend :3010, API :8010):

```bash
# 1. event loop must stay responsive during a preview
(for i in $(seq 1 60); do curl -s -o /dev/null -w '%{time_total}\n' localhost:8010/healthz; done > /tmp/lat.txt) &
curl -s -o /dev/null "localhost:8010/api/pipelines/load_test_10m/preview?limit=100" -H "Authorization: Bearer $TOKEN"
sort -g /tmp/lat.txt | tail -1     # PASS: stays ~0.005s. Today: 1.38s

# 2. preview memory must land on the preview worker, not the API
docker stats --no-stream dte047-backend-1 dte047-preview-worker-1

# 3. a preview must not queue behind a long run
curl -X POST .../load_test_10m/trigger …      # occupies the run queue
time curl -s ".../load_test_10m/preview?limit=100"   # PASS: still ~2s
```

Check 1 is the headline: it is the measurement that motivated this plan, and the number that
proves it worked.

## Non-goals

- **Sampling / approximate preview.** Bounding the *work* (scan N rows, label results as
  sampled) is a real fix for a real problem, but it changes aggregate semantics and needs UI
  work. Separate plan.
- **DuckDB `memory_limit` / statement timeouts.** Worth doing, but once preview is off the API
  process the urgency drops. Fold into the sampling plan.
- **Caching preview results** across identical requests.
- **Per-tenant preview quotas.** Revisit if one tenant saturates the preview pool.
- **Moving `step-schemas` to a queue** — see above.
- Frontend changes: the 202 path is additive and unused until a preview actually exceeds the
  wait budget.
