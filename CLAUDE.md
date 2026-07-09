# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install
uv pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file or test
pytest tests/unit/test_compiler.py
pytest tests/unit/test_compiler.py::test_join_inner

# Run with coverage
pytest --cov=dte

# Skip postgres integration tests (requires DATABASE_URL)
pytest -m "not integration"

# Start API server
uvicorn dte.api.main:app --reload

# Run DB migrations (requires DATABASE_URL)
alembic upgrade head

# Frontend (Next.js) — see frontend/README.md for details
cd frontend && pnpm install && pnpm dev   # http://localhost:3000
cd frontend && pnpm gen:types             # regen types (backend must be up)
```

## Frontend

Next.js 16 app under `frontend/`. Talks to the FastAPI at `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). CORS is wired via `DTE_CORS_ORIGINS` env on the backend (default `http://localhost:3000`). Types in `frontend/src/lib/api-types.ts` are generated from `/openapi.json` — regenerate whenever backend schemas change.

The design system under `frontend/src/components/ui/` is intentionally portable: import only from itself + `lib/cn.ts`, all colors/fonts token-driven via CSS vars in `globals.css`. Copy that folder + `globals.css` to reuse in other projects.


## Architecture

DTE is a batch data transformation engine. A **Pipeline** (Pydantic model) describes sources, ordered transform steps, and an output target.

### Full data flow

```
DltSource config(s)
    ↓
dlt_loader.load_source() → ibis.Table per source (loaded into shared DuckDB connection)
    ↓
compile_pipeline(pipeline, tables) → ibis.Table (transformed)
    ↓
DuckDBEngine.execute_to_json() → output file + row count
```

### Key modules

**`dte/models/pipeline.py`** — the pipeline spec. `Pipeline.steps` is `list[dict]` (not a typed Union) because the `map` op requires a sub-discriminator on `mode` that Pydantic's discriminated union can't handle with a shared `op` key. The compiler parses each step dict by `op`/`mode`.

**`dte/sources/dlt_loader.py`** — universal source loading via dlt. `load_source(DltSource, ibis_con)` runs a dlt pipeline into the shared DuckDB connection (`con.con` is the raw `duckdb.DuckDBPyConnection`) and returns an `ibis.Table`. Currently implements `filesystem` source type; add new source types here. Do **not** write custom connector classes — extend this file with new dlt sources.

**`dte/compiler/ibis_compiler.py`** — `compile_pipeline(pipeline, tables)` maintains a **named registry** (`dict[str, ibis.Table]`) instead of a rolling variable. Each step reads from and writes back to the registry via `current_key`. Join steps write their result under `output_id` and update `current_key`. This allows multi-source pipelines.

- Filter and expression-map steps escape to raw SQL via `con.create_view()` + `con.sql()` — Ibis has no SQL string parser. This is the seam for future distributed backends (Spark, Trino).
- Pivot uses `con.con.execute("CREATE OR REPLACE TEMP TABLE ... AS PIVOT ...")` — dynamic PIVOT cannot be a view in DuckDB, and `con.sql()` fails because sqlglot can't subquery a PIVOT node.

**`dte/engine/duckdb_engine.py`** — wraps `ibis.duckdb.connect()`. Exposes `con` property (the ibis backend) for use by `dlt_loader`. Only responsible for execution and output — does not load sources.

**`dte/store/`** — `PipelineStore` and `RunStore` Protocols in `base.py`. `memory.py` is the default (used in all tests). `postgres.py` is the production backend (SQLAlchemy async, requires `DATABASE_URL`). The active backend is wired in `dte/api/deps.py` and injected into routes via FastAPI `Depends()`.

**`dte/api/`** — FastAPI app. Routes use `Depends(get_pipeline_store)` and `Depends(get_run_store)`. Tests override these with `app.dependency_overrides`. `_execute_pipeline` runs as an `asyncio.create_task` — trigger returns `run_id` immediately, caller polls `GET /api/runs/{run_id}`.

### Step dispatch

```python
op = step["op"]    # "filter"|"rename"|"retype"|"map"|"sort"|"aggregate"|"join"|"pivot"
mode = step.get("mode")   # "lookup"|"expression"|"calculation"  — map steps only
```

### dlt column naming

dlt normalises nested JSON keys with `__` (e.g. `{"order": {"amount": 1}}` → column `order__amount`). `_resolve_field()` in the compiler falls back to `__`-joined names when struct traversal fails, making it compatible with both ibis struct columns and dlt-flattened columns.

### Ibis version notes

- ibis ≥ 9: use `ibis.cases(*[(condition, value), ...], else_=default)`, **not** `ibis.case()`
- `table.rename({new_name: old_name})` — ibis rename direction is reversed from intuition

## API surface

```
POST   /api/pipelines                     create pipeline
GET    /api/pipelines                     list pipelines
GET    /api/pipelines/{id}                get pipeline
POST   /api/pipelines/{id}/trigger        start async run → {run_id}
GET    /api/runs/{run_id}                 poll run status
```

Missing (tracked in `plans/005-missing-api-endpoints.md`):
- `POST /api/schema/infer` — field tree from a DltSource config
- `GET  /api/pipelines/{id}/preview` — compile + execute on sample rows
- `GET  /api/pipelines/{id}/runs` — run history per pipeline

## Development workflow

### Before implementing any feature

Write a plan to `plans/<NNN>-<feature-name>.md`. Plans must include: problem statement, architecture change, explicit task list with branch names, and files changed/deleted. See existing plans for format.

### Worktree workflow (required for all feature work)

```bash
# Start
git worktree add ./worktrees/<name> -b feature/<name>

# Work in worktree, run tests
pytest -x

# Merge back
cd /Users/bhavaniravi/projects/dte
git merge feature/<name> --no-ff
git worktree remove worktrees/<name>
git branch -d feature/<name>
```

Every non-trivial change gets its own worktree. Do not develop directly on `main`.

## Store / database

Alembic manages Postgres schema. Run `alembic upgrade head` with `DATABASE_URL=postgresql+asyncpg://...` set. Without `DATABASE_URL`, the API uses the in-memory store and no Postgres is needed. Postgres integration tests (`tests/integration/test_store_postgres.py`) are skipped automatically when `DATABASE_URL` is unset.

## TDD convention

Write failing tests first. Implement until they pass. Stop — do not add features beyond what tests require.
