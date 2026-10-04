# Scaling and execution

DTE runs inside Airflow, so execution scales the way Airflow does. Every pipeline run is a
task of the `dte__<pipeline>` DAG, executed by whatever executor Airflow is configured with.

## Where runs execute

| Install | Executor | Where a pipeline runs |
| --- | --- | --- |
| `docker compose up` | `LocalExecutor` | Inside the `airflow-scheduler` container |
| Kubernetes | `KubernetesExecutor` / `CeleryExecutor` | A task pod / Celery worker |

Preview (sample rows while editing) runs in the Airflow api-server, not in a task.

## Things that must be shared

- **`local_fs` paths.** A `local_fs` source or destination is read and written by whichever
  container runs the task. Mount the same volume on every Airflow component (compose mounts
  `/tmp/dte-samples`), or use an object store.
- **`DTE_ARTIFACT_DIR`.** The extract/structure cache. Point every component at the same
  volume, or Run re-pays for model calls Preview already made.

## Concurrency

- A schedule with **Overlap: Skip** runs with `max_active_runs=1`.
- Use Airflow pools and `parallelism` settings to cap how many DTE runs execute at once.

## Cancelling

**Cancel** in the DTE UI marks the dag run failed; Airflow stops the running task.
