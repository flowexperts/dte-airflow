# Scaling and execution

Every pipeline run is a task of the `dte__<pipeline>` DAG, run by whatever executor Airflow uses.

| Install | Executor | Where a pipeline runs |
| --- | --- | --- |
| `docker compose up` | `LocalExecutor` | Inside the `airflow-scheduler` container |
| Kubernetes | `KubernetesExecutor` / `CeleryExecutor` | A task pod / Celery worker |

Preview runs in the api-server, not in a task.

## Must be shared

- `local_fs` paths: read and written by whichever container runs the task. Mount the same volume on every component (compose mounts `/tmp/dte-samples`), or use an object store.
- `DTE_ARTIFACT_DIR`: the extract/structure cache. Share one volume, or Run re-pays for model calls Preview already made.

## Memory and time limits

- Each run and each preview gets its own DuckDB connection, capped at `DTE_DUCKDB_MEMORY_LIMIT` (default `2GB`). Past the cap it spills to `DTE_DUCKDB_TEMP_DIR` instead of exhausting the worker. Size the worker for (concurrent runs × the cap), and give the temp dir disk.
- A run is failed after its schedule's timeout, or `DTE_RUN_TIMEOUT_SECONDS` (30 min) if none is set.
- Preview returns a 504 after `DTE_PREVIEW_TIMEOUT_SECONDS` (30 s), so a slow source can't hold the api-server.

## Concurrency

- One run at a time per pipeline (`max_active_runs=1`) unless its schedule sets Overlap: Allow.
- Cap concurrent dte runs with Airflow pools and `parallelism`.

## Cancelling

Mark the dag run failed in Airflow, or `POST /dte/api/runs/{run_id}/cancel`.
