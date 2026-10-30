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

## Concurrency

- Overlap: Skip runs with `max_active_runs=1`.
- Cap concurrent dte runs with Airflow pools and `parallelism`.

## Cancelling

Mark the dag run failed in Airflow, or `POST /dte/api/runs/{run_id}/cancel`.
