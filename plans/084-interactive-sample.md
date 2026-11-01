# Plan 084: Interactive paths run on a source sample, not the live source

## Context

When you open the pipeline editor on a `rest_api` source (for example the PyPI downloads source), the whole Airflow api-server freezes, and that includes run history. There are three causes, and they stack:

1. **The event loop is blocked.** `schema/infer`, `sources/{id}/schema`, `pipelines/step-schemas`, `pipelines/dry-run` and `pipelines/{id}/preview` are all `async def`. Each one calls the synchronous `load_source(...)` and `.execute()` inline (`dte/api/routes/schema.py:69`, `sources.py:182`, `pipelines.py:765,973,995,915`). DTE is mounted *inside* Airflow's FastAPI app, so one slow HTTP fetch stalls every request on that worker: run history, Airflow's own UI, and health checks.
2. **The work has no upper bound.** `_load_rest_api` (`dte/sources/loader.py:284`) runs `pipeline.run(resource)` with no limit, so it paginates the entire API to show 20 rows. `_load_mongodb` scans the whole collection. The `?limit=` on preview bounds the rows returned, not the work done.
3. **The same download repeats.** Each request builds a fresh `DuckDBEngine`. When the editor opens, it fires AutoInferSchemas (one call per source), step-schemas and dry-run, and each edit fires them again. Every one of those calls downloads the source again.

A queue of workers (the design in plan 049, procrastinate, before the move to Airflow) only addresses cause 1. The editor would still wait on an unbounded download that repeats every time. It would also add a deployable, a results table, and seconds of pickup latency to a feedback loop that should take one keystroke.

**The better method:** interactive paths never read the live source. They read a **bounded, cached sample snapshot**. Only two things touch the live source: real runs, and an explicit "refresh sample". This is how dbt Cloud, Hex and Airbyte handle the same problem.

## Architecture

```
editor (infer / step-schemas / dry-run / preview)
   │
   ▼  anyio.to_thread.run_sync(..., limiter=INTERACTIVE_LIMITER)   ← loop never blocks
interactive_tables(sources)
   ├─ lazy source (filesystem, s3/gcs/azure/sftp, sql_database, documents)
   │     → load_source() as today   (a view / pushdown, so LIMIT already bounds it)
   └─ eager source (rest_api, mongodb)
         → $DTE_ARTIFACT_DIR/samples/<key>.parquet exists and is fresh?  read_parquet view
         → otherwise, single-flight fetch: load_source(..., sample=N) → write parquet → view

DtePipelineOperator (a real run)  → after loading, write table.limit(N) to the same sample path
                                     (so the editor is warm after any run, at no extra cost)
```

- **key** = `sha256(source_type, config, table, connection_id)`. If you edit the source config, the key changes and a fresh sample is fetched automatically.
- **Bounded fetch**: dlt's `resource.add_limit(max_items=pages, max_time=seconds)` for rest_api, and `.find(filter).limit(n)` for mongo. A throwaway `pipelines_dir` keeps the dlt state used by previews out of the state used by runs, following the same pattern as `writers/postgres.py`.
- **Dedicated `anyio.CapacityLimiter`** (`DTE_INTERACTIVE_CONCURRENCY`, default 4). Previews can't use up the default threadpool that Airflow's own sync routes share. Excess work queues and does not pile up.
- **Time budget**: the fetch keeps running in its thread. If it takes longer than `DTE_SAMPLE_WAIT_SECONDS` (default 10), the request returns `{error, sampling: true}`. The frontend retries, and the next call hits the cache.
- **Shared storage already exists.** `DTE_ARTIFACT_DIR` is the named volume shared by the api-server and the scheduler (it already holds the extract cache), so runs and the editor see the same samples.
- **Single-flight**: a per-key `threading.Lock` makes the burst of N calls when the editor opens trigger one fetch instead of N.

## Tasks

| # | Task | Files | Branch |
|---|---|---|---|
| 1 | Move every `load_source`/`.execute()` in the interactive routes into `anyio.to_thread.run_sync` with a module-level `CapacityLimiter`. This ships alone and fixes the hang | `dte/api/routes/{pipelines,schema,sources}.py`, `dte/api/interactive.py` (limiter + `run_interactive` helper) | `feature/084-interactive-sample` |
| 2 | `load_source(..., sample: int \| None)`: `add_limit` for rest_api, `.limit` for mongo, throwaway `pipelines_dir`. Other loaders ignore it | `dte/sources/loader.py` | `feature/084-interactive-sample` |
| 3 | `dte/sources/sample.py`: `sample_key`, `load_interactive(source, registry, conn, creds, table)` with parquet cache, TTL (`DTE_SAMPLE_TTL_SECONDS`, default 24h), single-flight lock and wait budget. Interactive routes call it instead of `load_source` | `dte/sources/sample.py`, the same three route files | `feature/084-interactive-sample` |
| 4 | The operator writes a sample after a successful load of an eager source | `dte/airflow/runner.py` | `feature/084-interactive-sample` |
| 5 | `POST /api/sources/{id}/sample:refresh` (deletes the cache entry and refetches). The editor gets a "Sampled N rows · <age> · Refresh" chip and retries while `sampling: true` | `dte/api/routes/sources.py`, `frontend/src/components/pipeline/schema-sync.tsx`, `pipeline-preview.tsx` | `feature/084-interactive-sample` |
| 6 | Docs: update the `backend/CLAUDE.md` loader section and the API table. Mark plan 049 superseded | `backend/CLAUDE.md`, `dte/api/CLAUDE.md`, `plans/049-*.md` | `feature/084-interactive-sample` |

Order: task 1 lands first and removes the outage by itself. Tasks 2 and 3 remove the cost. Tasks 4 and 5 are about UX.

## Non-goals (deliberate ceilings)

- **Sampling lazy sources.** An aggregate over a 10M-row file still scans the whole file (cause 1 of plan 049). Thread offload stops it freezing the server, but it isn't bounded. Add DuckDB `memory_limit` and a statement timeout when this shows up in practice.
- **GIL contention.** dlt normalisation of a bounded sample in a thread is small. If a single huge page (one 100 MB response) still hurts, move the sample fetch into a `ProcessPoolExecutor`. It writes parquet anyway, so the interface stays the same.
- **A worker or Airflow-task fetch for samples.** Only needed if samples become expensive enough to need isolated resources. The `sample.py` seam is where that would go.

## Verification

- **Unit** (TDD, write these first):
  - `test_interactive_offload.py`: while a fake slow `load_source` (sleeping 3 s) is running, a concurrent `GET /api/me` answers in under 100 ms.
  - `test_sample_cache.py`: two concurrent loads trigger the fake loader once (single-flight). Changing the config produces a new key. A stale TTL triggers a refetch. Going over the budget returns `sampling: true`.
  - `test_loader_sample.py`: rest_api with `sample=` stops after N pages against a paginating fake server (reuse the patterns in `tests/unit/test_rest_credentials_merge.py`).
- **Suites**: `uv run pytest -x` and `uv run pytest tests/scenarios -m scenario`. Preview response bodies stay unchanged for lazy sources.
- **End to end** (compose, run from the worktree):
  ```bash
  (for i in $(seq 60); do curl -s -o /dev/null -w '%{time_total}\n' localhost:8080/api/v2/monitor/health; done > lat.txt) &
  # open the PyPI pipeline in the editor; meanwhile load run history
  sort -g lat.txt | tail -1        # PASS: under 0.1s (today: the whole fetch duration)
  ls $DTE_ARTIFACT_DIR/samples/    # one parquet per eager source
  ```
  The second time you open the editor, schema and preview come back in under 1 s, with no outbound HTTP (check `docker compose logs`).
