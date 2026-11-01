# CLAUDE.md

Guidance for Claude Code in this repo. Area-specific rules live in
path-scoped `CLAUDE.md` files that load automatically when you touch that
directory:

```
frontend/CLAUDE.md            Airflow react_apps plugin, design system, builder (+ DESIGN.md)
backend/CLAUDE.md             data flow, compiler, ibis, field refs, extract/structure
backend/dte/api/CLAUDE.md     HTTP surface
backend/dte/evals/CLAUDE.md   eval sets, sweeps, comparison, promote, matrix
backend/dte/sources/CLAUDE.md sources, destinations, connections, credentials
backend/dte/store/CLAUDE.md   stores, SQLModel, Alembic
backend/tests/CLAUDE.md       testing tiers
docs/worktrees.md             worktree + compose setup (read before the first run)
```

## Repo layout

```
backend/       Python package `dte`, alembic, tests, Dockerfile
frontend/      React UI, built as an Airflow react_apps plugin bundle
docker-compose.yml   whole stack (postgres + Airflow with DTE as a plugin)
plans/         feature plans (numbered)
```

All Python paths below are relative to `backend/`.

## Commands

```bash
# Whole stack: postgres :5432 + Airflow 3.3 (api-server :8080, scheduler,
# dag-processor). scripts/bootstrap.sh writes .env (secrets + admin password);
# compose refuses to start without it. DTE UI at /plugin/dte, API at /dte/api.
scripts/bootstrap.sh
docker compose up -d --build
docker compose logs -f airflow-apiserver
# ./backend/dte is bind-mounted; restart to pick up Python changes:
docker compose restart airflow-apiserver airflow-scheduler airflow-dag-processor

# Backend
cd backend && uv sync --all-extras
uv run pytest                      # unit; scenarios excluded by default
uv run pytest tests/scenarios -m scenario -v
uv run pytest -m "not integration" # skip postgres tests
dte db upgrade                     # migrate the `dte` schema (needs DTE_DATABASE_URL or Airflow config)
dte validate pipelines/*.yaml      # pipeline files (plan 090), what CI runs
dte run <file> [--sample N]        # run a pipeline file locally; no Postgres, conns from AIRFLOW_CONN_*
dte export --out pipelines/        # DB -> files, once, before DTE_PIPELINE_STORE=file

# Frontend (Airflow plugin bundle; rebuild the image to ship it)
cd frontend && pnpm install && pnpm build
./scripts/gen-api-types.sh   # regen api-types.ts from app.openapi(); no server
```

## Architecture in one paragraph

DTE is a batch data transformation engine. A **Pipeline** (Pydantic) names
sources, ordered transform steps and an output. Sources load into a shared
DuckDB connection as ibis tables (`dte/sources/loader.py`), the compiler
(`dte/compiler/ibis_compiler.py`) folds steps over a named table registry, and
`dte/engine/duckdb_engine.py` executes and writes. DTE runs as an **Airflow
3.3 app** (plan 065, all in `dte/airflow/`): a plugin mounts the API at `/dte`
and registers the UI as a native `react_apps` bundle (plan 066, no iframe), a DAG factory turns every pipeline (and enabled schedule) into a
`dte__<id>` DAG, and `DtePipelineOperator` runs it via `dte/airflow/runner.py`.
Airflow owns auth, connections, scheduling and run history; DTE's tables live
in the `dte` schema of the Postgres `DTE_DATABASE_URL` names (its own database
or Airflow's metadata DB), with `run_results` holding the per-run outputs
Airflow can't. Tests inject fake stores. Details in
`.claude/rules/architecture.md`.

## Development workflow

**Before implementing any feature**, write a plan to
`plans/<NNN>-<feature-name>.md`: problem statement, architecture change,
explicit task list with branch names, files changed/deleted.

**Every non-trivial change gets its own worktree. Do not develop on `main`.**

```bash
git worktree add ./worktrees/<name> -b feature/<name>
cd worktrees/<name>/backend && uv run pytest -x
git merge feature/<name> --no-ff
git worktree remove worktrees/<name> && git branch -d feature/<name>
```

A fresh worktree needs four setup steps and compose must be run *from* it —
see `.claude/rules/worktrees.md` before the first run.

## TDD convention

Write failing tests first. Implement until they pass. Stop — do not add
features beyond what tests require.
