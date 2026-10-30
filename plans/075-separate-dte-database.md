# Plan 075: DTE's tables in any Postgres database

Branch: `feature/pip-install` (worktree `worktrees/pip-install`), on top of the
`DTE_DATABASE_URL` rename (`a59da13`, not yet merged to `dte-airflow`).

## Problem

`DTE_DATABASE_URL` has to be Airflow's metadata database today. One query
forces it: `PostgresRunStore` joins Airflow's `dag_run` to `dte.run_results`
in SQL (`_RUNS_SQL`, `dte/store/postgres.py`). So DTE's DAG parsing and tasks
run with credentials that reach every Airflow table, connections included —
the access Airflow 3 deliberately takes away from task code.

Nothing else couples the two: alembic only touches the `dte` schema, and
connection listing (`connection_store`, `model_connections`) already goes
through Airflow's own session in the api-server.

## Goal

`DTE_DATABASE_URL` can point at any Postgres — a separate `dte` database with
its own role is the recommended setup. DTE's credentials never touch Airflow's
tables; only Airflow's own code (in Airflow's own process) reads `dag_run`.

## Who reads runs, and from where

| Caller | Process | Today | After |
|---|---|---|---|
| Runs pages, run detail, evals, sweeps (`get_run_store`) | api-server | SQL join on `dag_run` | dag runs via Airflow's session + `run_results` from DTE's DB, merged in Python |
| Regression check (`DtePipelineOperator._regression`) | worker (task) | `PostgresRunStore.list_for_eval_set` | `run_results` only |
| `dte db upgrade` | CLI | `DTE_DATABASE_URL`, else Airflow's URL | unchanged |

## Design

### 1. Dag-run reader: `dte/airflow/dag_runs.py` (new)

```python
async def dag_runs(dag_ids: list[str] | None = None, run_id: str | None = None) -> list[dict]:
    """Dag runs of DTE DAGs, read with Airflow's own session (api-server only)."""
```

- `select(DagRun.run_id, dag_id, state, queued_at, start_date, end_date, run_type, conf)`
  filtered to `dag_ids`, or to `dag_id LIKE 'dte\_\_%'` when none; optional `run_id`.
- Sync ORM, so it runs in `asyncio.to_thread`. Enum columns become plain strings.
- Why the ORM, not the REST API: the api-server already uses this pattern
  for connections; it needs no forwarded token, adds no HTTP hop, and still
  keeps DTE's credentials off Airflow's tables.

### 2. Run store: `dte/store/postgres.py`

- `PostgresRunStore(session_factory, dag_runs=airflow_dag_runs)` — the reader
  is injected so tests pass a fake.
- `_merge(dag_run, result | None) -> dict` reproduces `_RUNS_SQL` exactly:
  - status: finished dag run → the operator's `completed` /
    `completed_with_warnings` / `failed_quality` if recorded, else
    `completed` / `failed` from the dag run state; `running` → `running`;
    anything else → `pending`
  - `started_at = start_date or queued_at`, `finished_at = end_date`
  - `pipeline_id`, `revision_id`, `params`, `eval_set_id`, `sweep_id` fall back
    to the dag id / `conf` so queued runs already show them
  - `scheduled = run_type == "scheduled"`
- Results: `SELECT … FROM run_results WHERE run_id IN :ids` (expanding bind;
  skipped when there are no ids).
- Methods keep their signatures and return shapes:

| Method | Dag runs fetched | Filter in Python |
|---|---|---|
| `get(id)` | `run_id=id` | — |
| `list_for_pipeline(pid)` / `count_for_pipeline` | `dag_ids=[dte__pid]` | — |
| `list_for_eval_set(esid)` | all `dte__*` | `eval_set_id == esid` |
| `list_for_sweep(sid)` | all `dte__*` | `sweep_id == sid`, oldest first |
| `list_sweep_runs_for_root(root)` | all `dte__*` | same rule as today's SQL |

  Sort `started_at DESC` with NULLs first (Postgres' default), then
  limit/offset. `delete_for_pipeline`, `get_quality` and
  `PostgresRunEventStore` only touch `run_results` — unchanged.
- `ponytail:` the eval-set and sweep listings scan every `dte__*` dag run;
  move the filter into the `DagRun` query (conf JSON) if run counts grow
  into the tens of thousands.
- `_RUNS_SQL` is deleted.

### 3. Tasks never read `dag_run`: `dte/airflow/results.py`, `operators.py`

- New `eval_history(engine, eval_set_id, limit=50)`:
  `SELECT run_id AS id, config_digest, labels_version, scores FROM run_results
  WHERE eval_set_id = :e AND scores IS NOT NULL ORDER BY created_at DESC LIMIT :n`.
  Finished eval runs are fully recorded there by the operator itself, which is
  all `detect_eval_regression` reads.
- `_regression` uses it with the existing sync engine; no async store, no
  `asyncio.run`.

### 4. Database setup and docs

- `dte/airflow/db.py`: docstring says any Postgres; the `RuntimeError` text
  stops calling it "the metadata DB". `search_path=dte,public` stays (harmless
  in a separate database).
- Install doc, secrets doc, README, site quickstart, `backend/dte/store/CLAUDE.md`:
  `DTE_DATABASE_URL` is DTE's own database; recommended setup is
  `CREATE DATABASE dte` + a role that owns it, with no grants on Airflow's
  database. Pointing it at Airflow's metadata DB still works.
- The README line becomes the one already sitting uncommitted in the main
  checkout (`…:5432/dte`), so the merge only needs that edit dropped.

## Tests (TDD, failing first)

- `tests/unit/test_run_merge.py` (no Postgres, no Airflow):
  - `_merge` table-driven over dag run states × recorded statuses, plus the
    timing and conf fallbacks.
  - The store against a fake `dag_runs` and a stub results fetch: pipeline
    listing, get, count, eval-set filter, sweep order and root rule,
    pagination, a dag run with no result row (queued).
- `tests/unit/test_results.py`: `eval_history` on SQLite-compatible SQL is
  not possible (JSONB) — assert the operator passes `eval_history`'s rows to
  `detect_eval_regression` instead, with `eval_history` faked.
- Integration (`tests/integration/test_store_postgres.py`,
  `test_store_evals_postgres.py`): their run tests call `create` / `update`,
  which the store lost in plan 065, so they fail today. Rewrite them to seed
  `run_results` and pass a fake `dag_runs`.
- Smoke (`scripts/test-pip-install.sh`): DTE gets its own `dte` database and
  `dte` role with no access to the `airflow` database;
  `DTE_DATABASE_URL=postgresql://dte:dte@pg/dte`. Every pipeline run must
  still reach `completed`, and a new check lists a pipeline's runs through
  `GET /dte/api/pipelines/{id}/runs`.

## Out of scope

- Reading dag runs through Airflow's REST API (only needed if DTE's API ever
  runs outside the api-server).
- Moving an existing install's `dte` schema to a new database (`pg_dump -n dte`
  then restore works; document it in upgrading.md if anyone asks).

## Files

- New: `backend/dte/airflow/dag_runs.py`, `backend/tests/unit/test_run_merge.py`
- Edit: `backend/dte/store/postgres.py`, `backend/dte/airflow/{operators,results,db}.py`,
  `backend/tests/integration/{test_store_postgres,test_store_evals_postgres}.py`,
  `scripts/test-pip-install.sh`, `docs/user/self-hosting/{install-plugin,secrets}.md`,
  `README.md`, `site/` quickstart, `backend/dte/store/CLAUDE.md`
- Delete: `_RUNS_SQL`
