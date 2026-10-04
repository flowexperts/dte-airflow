# Plan 065 — DTE as an Airflow 3 app

## Context

DTE currently runs its own orchestration stack: a Procrastinate job queue and worker (`dte/worker/`), a cron tick scheduler (`dte/scheduling/`, `worker/scheduler.py`), a `runs`/`run_events` history with heartbeat and reaper, a Fernet-encrypted `connections` store, JWT auth with users, roles and tenants, and a standalone Next app. Airflow already does all of these. The goal is to make DTE an app that runs *inside* Airflow 3.1+:

- **UI:** the DTE UI becomes an Airflow plugin view.
- **Connections:** Airflow Connections replace the DTE connection store.
- **Runs:** transform, quality and eval pipelines (extract is a step inside them) run as Airflow DAGs through a DTE provider and operator.
- **Hard cut:** there is no standalone mode left behind.
- **Metadata:** DTE's own metadata lives in Airflow's metadata DB, in a separate `dte` Postgres schema.

DTE keeps only what Airflow has no equivalent for: pipelines, revisions, sources, destinations, lookup tables, dashboards, eval sets and examples, plus a slim run-results table for the scores and quality outputs that Airflow cannot hold.

## Target architecture

```
Airflow 3.1 api-server
 ├─ core Airflow UI + REST /api/v2 (auth, connections, dag runs, logs)
 └─ DTE plugin (entry point in dte pyproject)
     ├─ fastapi_apps: DTE FastAPI mounted at /dte/api   (pipelines, sources, evals…)
     │                + StaticFiles at /dte/ui           (Next static export)
     └─ external_views: "DTE" nav item -> /dte/ui
Airflow dag-processor
 └─ dte_dags.py  (DAG factory: one DAG per DTE pipeline/schedule, read from dte schema)
Airflow scheduler/executor
 └─ DtePipelineOperator -> dte.airflow.runner.run_pipeline (loader -> compiler -> engine -> contracts)
Postgres (Airflow metadata DB)
 └─ schema `dte` (own alembic_version table)
```

The whole integration lives in **one new subpackage, `backend/dte/airflow/`**, exposed through an `airflow` extra and `apache_airflow_provider` + `airflow.plugins` entry points in `backend/pyproject.toml`. There is no separate provider repo: `packages/dte-sdk` is a stub and gets deleted.

## Key design decisions

1. **The runner is extracted from `_run_body`** (`dte/api/routes/pipelines.py:1375`) into a sync `dte/airflow/runner.py::run_pipeline(pipeline, resolved_sources, resolved_dest, params, on_event) -> RunResult`.
   - It reuses what already exists:
     - `resolve_context`/`interpolate_pipeline` (`compiler/interpolate.py`)
     - `get_engine` (`engine/registry.py:29`)
     - `BackendRegistry`
     - `load_source` (`sources/loader.py:464`)
     - `compile_pipeline`
     - `engine.execute`
     - `evaluate_contracts` (`quality/evaluator.py:76`)
     - the eval body `_run_eval_body` (`pipelines.py:1562`)
   - It takes no stores and no `HTTPException`s.
   - Status mapping:
     - `failed_quality` raises `AirflowFailException`.
     - `completed_with_warnings` is task success with the warnings in the log and XCom.
     - Everything else is success.
2. **Connections go through one adapter function**, `dte/airflow/connections.py::to_dte(conn_id) -> (Connection, creds)`.
   - It maps Airflow's built-in conn types onto DTE's `ConnectionType` (`models/pipeline.py:17`) and returns creds in the same dict shapes `load_source`/writers use today (the SQL family is `{"url": ...}`).
   - The mapping is `postgres`, `mysql`, `sqlite`, `snowflake`, `google_cloud_platform`→bigquery/gcs, `aws`→s3, `wasb`→azure, `mongo`, `http`→rest_api, `fs`→local_fs.
   - No custom conn type, and the provider hooks aren't wrapped: the adapter reads `Connection` fields and extras.
   - The credentials for `ExtractStep` (the LLM API keys) also come from an Airflow connection.
3. **DAGs come from a factory**: `dte/airflow/dag_factory.py::build_dags()` plus a one-line `dags/dte_dags.py` that calls it into `globals()`.
   - Every pipeline gets a manual DAG, `dte__<pipeline_id>` with `schedule=None`, so "Run" in the UI is an Airflow DAG trigger.
   - Every enabled row in `schedules` gets `dte__<pipeline_id>__<schedule_id>` with:
     - `CronTriggerTimetable(cron_expr, timezone)`
     - `catchup=False`
     - `max_active_runs=1` when `overlap="skip"`
     - `params` taken from the schedule, with `eval_set_id` passed in the operator args
   - Every DAG is tagged `dte`, `dte-pipeline:<id>` and `dte-type:<transform|quality|eval>`.
   - The DB is read at parse time, so a pipeline or schedule change shows up after the next dag-processor parse, roughly 30s. `# ponytail:` note that if the pipeline count ever makes parsing slow, switch to DAG files written on save.
4. **One operator, `DtePipelineOperator(pipeline_id, revision_id=None, eval_set_id=None)`**, handles all pipeline types.
   - It loads the pipeline and revision from the `dte` schema, resolves each source's and destination's `conn_id` via `to_dte`, and runs the runner with `context["params"]` (which carries the DAG-run `conf`).
   - Per-step events go to the task log.
   - It writes a `run_results` row and returns a small XCom: rows_written, quality summary, scores.
5. **Metadata lives in Airflow's DB, schema `dte`.**
   - The stores keep SQLModel and Postgres. The engine URL comes from Airflow's `sql_alchemy_conn`, with `search_path=dte`.
   - Alembic uses `version_table_schema="dte"`, so it never touches Airflow's migrations. It runs via a `dte db upgrade` CLI (or a plugin `on_load` check that refuses to start if the schema is behind).
6. **Run history belongs to Airflow.**
   - `runs` and `run_events` are replaced by `dte.run_results(dag_id, run_id, pipeline_id, revision_id, rows_written, location, quality_checks, scores, sweep_id, labels_version, config_digest, sql_query)`.
   - Status and timings come from Airflow `/api/v2/dags/{id}/dagRuns`.
   - Eval comparisons and sweeps read `run_results`. A sweep triggers N DAG runs with `conf`.
7. **Auth belongs to Airflow.**
   - `get_current_user`/`requires` (`api/deps.py:111`, `security/permissions.py`) are replaced with Airflow 3's FastAPI security dependencies (the auth manager user and DAG access checks).
   - `pipeline:*` perms map to DAG read, edit and trigger on `dte__*` DAGs. Users, roles, tenants, row-level security and FastAdmin are dropped.
8. **The UI is a static Next export, served by the plugin and shown as an `external_view`.** The Next app can't become an Airflow `react_app` (that needs an ESM bundle) without a rewrite, so it ships as a static site instead.
   - The frontend calls `/dte/api/*` for DTE entities, and Airflow `/api/v2/*` directly for connections, triggers, runs and logs. It uses relative URLs with the same origin and Airflow's token.

## Tasks (worktree + branch each, TDD)

**0. Spike** (`feature/airflow-spike`), 1 day, throwaway.
- Build a minimal Airflow 3.1 plugin with `fastapi_apps` + `external_views` + static files.
- Confirm how the iframe gets Airflow auth (the `_token` cookie vs the header) and the exact security dependency names to import.
- Findings update decisions 7 and 8 before task 5.

**1. Runner extraction** (`feature/airflow-runner`)
- Tests: `tests/airflow/test_runner.py` runs a local_fs transform, a quality pipeline with a failing check, and an eval pipeline on fixtures, with no stores involved.
- Add `dte/airflow/runner.py`. Make `_run_body` call the runner, so the API keeps working until task 5.

**2. Connection adapter** (`feature/airflow-connections`)
- Tests: one parametrized case per conn type, from an Airflow `Connection(...)` object to the expected `(ConnectionType, creds)`.
- Add `dte/airflow/connections.py`. `Source`/`Destination` get a `conn_id: str` in place of the `connection_id` FK (migration).

**3. Schema move + slim tables** (`feature/airflow-schema`)
- Alembic env gets `version_table_schema="dte"` and `search_path`.
- A migration creates `run_results` and drops `runs`, `run_events`, `connections`, `users`, `roles`, `user_roles`, `tenants`, `tenant_secret_keys`, the RLS policies, the Procrastinate tables and the runtime columns on `schedules` (`next_run_at`, `last_run_id`, `last_fired_at`).
- Data migration for existing installs: a one-off script turns each `connections` row into an Airflow connection (`airflow connections import` JSON).

**4. Operator + DAG factory + provider** (`feature/airflow-provider`)
- Tests:
  - `DagBag` over `dags/dte_dags.py` imports with no errors and the expected dag_ids.
  - `dag.test()` on a local_fs pipeline writes its output and a `run_results` row.
  - A quality failure fails the task.
- Add `dte/airflow/{operators.py,dag_factory.py,provider.py}` and `dags/dte_dags.py`, plus the pyproject `airflow` extra and entry points.

**5. API as a plugin** (`feature/airflow-plugin-api`)
- Add `dte/airflow/plugin.py` (`AirflowPlugin` with `fastapi_apps`, `external_views`) and swap auth dependencies across `dte/api/routes/*`.
- Delete:
  - `api/routes/auth.py`
  - the connections routes
  - the run trigger, cancel and list routes and `_execute_pipeline`
  - the schedule tick logic
- Schedule routes stay as plain CRUD on the `schedules` table.
- Run-detail routes read `run_results`.

**6. Frontend as static export** (`feature/airflow-ui`)
- `output: "export"`, `basePath: "/dte/ui"`, relative API base.
- Move server fetches into SWR client components, and switch `[id]` routes to `?id=`.
- Delete:
  - `proxy.ts`
  - `(auth)/login`
  - `profile`
  - `(app)/connections/*`
  - the marketing components in `frontend/src/components/marketing/`
  - the `docs-assets` route handler
- Rewire:
  - The connection pickers list Airflow `/api/v2/connections`.
  - "Run" calls `POST /api/v2/dags/dte__<id>/dagRuns`.
  - The runs tab lists Airflow dagRuns joined with `run_results`, and "logs" links into the Airflow grid.
- Regenerate the API types.

**7. Delete the old orchestration** (`feature/airflow-cleanup`)
- Delete:
  - `dte/worker/`, `dte/scheduling/` (keep cron validation only if the schedule CRUD needs it; croniter already does)
  - `dte/secrets/` (if nothing else uses it), `dte/security/jwt.py` + `passwords.py`
  - `dte/tenancy.py`, the `TenantContextMiddleware`, `dte/admin/`
  - `packages/dte-sdk/`
  - the procrastinate/fastadmin/jwt deps
- Rewrite `docker-compose.yml` to: postgres + `airflow api-server`, `scheduler`, `dag-processor`, on an image built from `apache/airflow:3.1.x` + `pip install -e backend[airflow]`, with `dags/` mounted.
- Update CLAUDE.md files, ARCHITECTURE.md, README (the orchestrator claim) and `docs/user/pipelines/scheduling.md`.

## Critical files

- Modify:
  - `backend/dte/api/routes/pipelines.py` (the `_run_body` split; remove trigger/cancel)
  - `api/deps.py`, `api/main.py`, `api/routes/{schedules,runs,sources,destinations}.py`
  - `models/pipeline.py` (Source/Destination `conn_id`; Schedule runtime fields)
  - `store/postgres.py`, `store/base.py`, `alembic/env.py`
  - `backend/pyproject.toml`, `docker-compose.yml`
  - `frontend/next.config.ts`, `frontend/src/lib/api.ts`, `frontend/src/components/pipeline/{canvas,activity}.tsx`, `frontend/src/components/builder/schedules/*`
- Add: `backend/dte/airflow/{runner,connections,operators,dag_factory,provider,plugin}.py`, `dags/dte_dags.py`, `tests/airflow/*`.
- Delete: `dte/worker/`, `dte/scheduling/`, `dte/admin/`, `dte/tenancy.py`, the auth/JWT code, `frontend/src/proxy.ts`, the login/profile/connections pages, `packages/dte-sdk/`.

## Verification

1. `uv run pytest tests/airflow` covers the runner, adapter, DagBag and `dag.test()`.
2. `docker compose up -d --build`, then log in to Airflow at `:8080`. The "DTE" nav item loads `/dte/ui`.
3. Create a postgres connection in the Airflow UI, then create a source/destination in DTE that picks it. Build a transform pipeline with an `extract` step, click Run, and see the DAG run in the Airflow grid. Output lands and `run_results` has rows_written.
4. For a quality pipeline, a failing `fail` check turns the task red and a `warn` check stays green with the warning in the XCom.
5. For an eval pipeline, the scores appear in the DTE comparison view.
6. Add a `*/5 * * * *` schedule and confirm that `dte__<id>__<sid>` appears after the parse and fires.
7. `uv run pytest` passes with no references left to `procrastinate`, `jwt` or `tenancy`.

## Risks

- **Parse-time DB reads.** The factory reads the DB on every dag-processor parse. Use one query with a short timeout, and a failure raises an import error that is visible in the Airflow UI.
- **Running `airflow db reset`.** It won't drop the `dte` schema, but backups of the Airflow DB now include DTE data, which is intended.
- **Auth inside the iframe.** How the iframe gets auth is unverified until task 0.
