# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (uses uv venv at .venv/)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/unit/test_compiler.py

# Run a single test
pytest tests/unit/test_compiler.py::test_filter_step

# Run with coverage
pytest --cov=dte

# Start API server
uvicorn dte.api.main:app --reload

# Frontend (Next.js) — see frontend/README.md
cd frontend && pnpm install && pnpm dev   # http://localhost:3000
cd frontend && pnpm gen:types             # regen from live backend
```

## Frontend

Next.js 16 app under `frontend/`. Talks to the FastAPI at `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). CORS is wired via `DTE_CORS_ORIGINS` env on the backend (default `http://localhost:3000`). Types in `frontend/src/lib/api-types.ts` are generated from `/openapi.json` — regenerate whenever backend schemas change.

The design system under `frontend/src/components/ui/` is intentionally portable: import only from itself + `lib/cn.ts`, all colors/fonts token-driven via CSS vars in `globals.css`. Copy that folder + `globals.css` to reuse in other projects.

## Architecture

DTE is a batch data transformation engine. A **Pipeline** (Pydantic model) describes sources, an ordered list of transform steps, and an output target. The pipeline JSON is stored in-memory in Phase 1; future phases will persist to Postgres.

### Data flow

```
Pipeline JSON → compile_pipeline() → ibis.Table → DuckDBEngine.execute_to_json()
```

1. **`dte/models/pipeline.py`** — the pipeline spec. `Pipeline.steps` is `list[dict]` (not a Union type) because the `map` op requires a sub-discriminator on `mode`. The compiler is responsible for parsing each step dict by `op`/`mode`.

2. **`dte/compiler/ibis_compiler.py`** — translates step dicts into an `ibis.Table` expression chain. Filter and expression-map steps cannot be expressed as pure Ibis because Ibis has no SQL string parser; they fall back to `con.create_view()` + `con.sql()` against the DuckDB backend. This is the intended seam for future distributed backends (Spark, Trino) — replace those two helpers per backend.

3. **`dte/engine/duckdb_engine.py`** — wraps `ibis.duckdb.connect()`. Executes the compiled ibis expression and writes output. Does **not** load sources directly — that is dlt's job.

3a. **`dte/sources/dlt_loader.py`** — universal source loading via dlt. Any source (local file, S3, MongoDB, REST API) is described as a `DltSource` config; `load_source()` runs a dlt pipeline into the shared DuckDB connection and returns an `ibis.Table`. Integration tests use dlt's `filesystem` source pointed at `tmp_path` — no custom connector mocks needed.

4. **`dte/schema/inferrer.py`** — samples up to N rows from a JSON file, recursively flattens nested dicts into dot-notation keys (`user.address.city`), and infers types. Lists of dicts use the first element; lists of primitives become `{type}_list`. Type merge precedence: `null` → widened, `int+float` → `float`, anything else → `string`.

5. **`dte/api/`** — FastAPI app with in-memory `_pipelines` and `_runs` dicts on `main.py`. Trigger endpoint fires `asyncio.create_task`; the task runs the full compile+execute pipeline and updates run status. Routes import the stores directly from `main` to avoid circular imports.

### Step dispatch pattern

```python
# compiler reads op then mode for "map" steps
op = step["op"]                        # "filter" | "rename" | "retype" | "map" | "sort" | "aggregate"
mode = step.get("mode")                # "lookup" | "expression" | "calculation"  (map steps only)
```

### Ibis version note

This project uses ibis ≥ 9. The case expression API changed: use `ibis.cases(*[(condition, value), ...], else_=default)`, **not** `ibis.case()`.

### Dot-notation fields

`_resolve_field(table, "order.amount")` traverses struct columns in ibis. DuckDB's `read_json` loads nested JSON as struct columns, so dot-notation field paths in step configs (group_by, sort.by, aggregate.field) are resolved through this helper — not by string splitting at the SQL layer.

## Development workflow

### Before implementing any feature

1. Write a plan to `plans/<NNN>-<feature-name>.md` (see existing plans for format). Plans must include: problem statement, architecture change, explicit task list with branch names, and list of files changed/deleted.
2. Split the plan into tasks — each task maps to one branch and one focused PR.

### Worktree workflow (required for all feature work)

```bash
# Start a feature
git worktree add ./worktrees/dte-<feature> -b feature/<name>
cd ../dte-<feature>

# Work, then run tests
pytest -x

# Merge back from main repo
cd /Users/bhavaniravi/projects/dte
git merge feature/<name>
git worktree remove ../dte-<feature>
git branch -d feature/<name>
```

Every non-trivial change gets its own worktree. Do not develop directly on `main`.

## Source connectors

Do **not** write custom connector classes for individual data sources. Use **dlt** (dlthub) for all source loading. dlt ships connectors for S3, GCS, MongoDB, REST APIs, SQL databases, local filesystems, and more. The `DltSource` model in `pipeline.py` carries a `source_type` (dlt source name) and a `config` dict passed through to dlt. See `plans/001-dlt-source-integration.md` for the full architectural rationale.

## TDD convention

Tests are written before implementations. Write failing tests first, implement until they pass, stop. Do not add features beyond what tests require.
