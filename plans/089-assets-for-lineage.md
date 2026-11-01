# 089 — Pipelines declare Assets; downstream pipelines run on them

## Problem

- **No lineage between pipelines.** If pipeline A writes a table that
  pipeline B reads, the only coupling is two crons that hopefully line up.
  No Airflow Assets are emitted (`backend/dte/airflow/dag_factory.py`).
- **Unscheduled DAGs default to `max_active_runs=16`**
  (`dag_factory.py:49`), so several manual runs can write the same
  destination concurrently.

Airflow 3 Assets cover both lineage and data-aware scheduling, and they show
up in Airflow's UI with no DTE UI work.

## Decision

- Every pipeline's `run` task declares `outlets=[Asset(uri)]` for its
  destination, and `inlets` for each source it reads.
- URI is derived from the destination or source config, for example
  `postgres://<conn_id>/<schema>/<table>`, `file://<path>`, `s3://bucket/key`.
  One function, `asset_uri(target_or_source)`, lives in `dte/airflow/`.
- Schedule gets a third mode alongside cron and none: **"after upstream"**.
  The DAG's `schedule` is the list of input Assets the user picks
  (`schedule=[Asset(...)]`).
- `max_active_runs=1` for every DAG unless the schedule explicitly allows
  overlap.

Not doing: a DTE-side lineage graph. Airflow's Assets view is the graph.

## Tasks

### 1. Emit Assets — `feature/089-assets`
- Tests: `asset_uri` for each source and output type; a built DAG's task has
  the expected `outlets`/`inlets`.
- `dag_factory._dag_for`: pass `inlets`/`outlets` to `DtePipelineOperator`.

### 2. Asset-triggered schedule — `feature/089-asset-schedule`
- Model: `schedule.mode: "cron" | "assets"` plus `schedule.assets: list[str]`
  (lenient read: a missing mode means cron).
- `dag_factory`: `schedule=[Asset(u) for u in assets]` when the mode is assets.
- Frontend schedule card: an "After these pipelines finish" picker that lists
  other pipelines' output URIs.
- Test: a DAG built with the assets mode has an `AssetTriggeredTimetable`.

### 3. Overlap default — same branch as 1
- `max_active_runs=1` unless `schedule.overlap == "allow"`. Test updated.

## Files

Changed: `backend/dte/airflow/dag_factory.py`, `backend/dte/airflow/operators.py`,
the schedule model in `backend/dte/models/pipeline.py`, the frontend schedule
card, `docs/user/` scheduling page.

New: `backend/dte/airflow/assets.py` (only if `asset_uri` outgrows a function
in `dag_factory.py`).
