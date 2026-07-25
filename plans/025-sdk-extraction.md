# Extract `dte-sdk` as an open-source package

## Context

DTE today is a single Python package (`backend/dte/`) that mixes two very different concerns:

1. A **transformation core** — Pydantic models, an ibis-based compiler, dlt/DuckDB source loaders, a DuckDB engine, and a secret-resolver interface. Generic, reusable, interesting to the wider ecosystem.
2. A **product app** — FastAPI routes, Postgres stores, FastAdmin, JWT/RBAC. DTE-specific and may stay closed-source.

Goal: extract the core into a standalone SDK that orchestration tools (Airflow, Prefect, Dagster) can install to define sources/destinations/lookup tables and trigger pipelines from operator code, while the app stays private.

Exploration confirmed the split is clean: **zero imports** from `dte.models`/`dte.compiler`/`dte.sources`/`dte.engine`/`dte.secrets`/`dte.schema` into `dte.api`/`dte.store`/`dte.admin`/`dte.security`. The two-class `Base` (pure Pydantic) / `Table` (SQLModel `table=True`) pattern in `dte/models/pipeline.py` already isolates domain from persistence. `load_source(Source, con, creds)` and `compile_pipeline(Pipeline, tables, output, lookup_tables)` are already SDK-shaped — they take model instances, not store handles.

## Decisions

- **Layout:** uv workspace monorepo. `packages/dte-sdk/` alongside `backend/`.
- **Name:** package `dte-sdk`, import `dte_sdk`.
- **ORM classes:** SDK ships `*Base` (pure Pydantic) only. Table classes move to `backend/dte/store/models.py`.
- **Back-compat:** hard cut. All `dte.*` imports in the app are rewritten to `dte_sdk.*`. No shims.

## Target SDK surface

```
packages/dte-sdk/
  pyproject.toml
  src/dte_sdk/
    __init__.py                    # re-exports the public API
    models/
      __init__.py
      pipeline.py                  # PipelineBase + Step models (FilterStep, RenameStep, ...)
      source.py                    # SourceBase, SOURCE_CONNECTION_COMPAT, SourceKind
      destination.py               # DestinationBase, OutputTarget union, DESTINATION_CONNECTION_COMPAT
      connection.py                # ConnectionBase, ConnectionType, _DLT_CRED_CLASS
      lookup.py                    # LookupTableBase
    compiler/
      __init__.py
      ibis_compiler.py             # compile_pipeline, step dispatchers
    sources/
      __init__.py
      loader.py                    # load_source(Source, con, credentials)
      connection_test.py           # probe_connection
    engine/
      __init__.py
      base.py                      # BaseEngine
      duckdb_engine.py             # DuckDBEngine
      writers/                     # json_file, csv_file, excel_file, parquet_s3, postgres, sql_database
    secrets/
      __init__.py                  # get_secret_resolver() — lazy, no import-time env read
      base.py                      # SecretResolver Protocol
      env.py                       # EnvSecretResolver
      fernet.py                    # FernetSecretResolver
      encrypted_json.py            # EncryptedJSON TypeDecorator (opt-in, SQLAlchemy extra)
    schema/
      __init__.py
      inferrer.py                  # infer_from_json
  README.md                        # SDK usage examples (Airflow operator sketch)
  LICENSE                          # Apache-2.0 (proposed)
  tests/                           # migrated from backend/tests/unit/{compiler, sources, secrets}
```

Public API (from `dte_sdk/__init__.py`):

```python
from dte_sdk import (
    PipelineBase, SourceBase, DestinationBase, ConnectionBase, LookupTableBase,
    compile_pipeline, load_source, probe_connection,
    DuckDBEngine, BaseEngine,
    SecretResolver, EnvSecretResolver, FernetSecretResolver,
    infer_from_json,
)
```

## What stays in `backend/dte/`

- `dte/api/` — FastAPI app, unchanged in logic; imports rewritten to `dte_sdk`.
- `dte/store/` — Postgres stores + Protocols. **New file `dte/store/models.py`** owns the SQLModel `table=True` classes (`Pipeline`, `Source`, `Destination`, `Connection`, `LookupTable`), each `(XxxBase, table=True)` where `XxxBase` comes from `dte_sdk.models`. The `narrow_config()` helper on `Destination` stays here.
- `dte/admin/` — FastAdmin, unchanged.
- `dte/security/` — JWT/RBAC, unchanged.
- Alembic migrations — unchanged; column shapes don't move.

## Key files to change

**Move & split (with import rewrites):**
- `backend/dte/models/pipeline.py` → split into `packages/dte-sdk/src/dte_sdk/models/{pipeline,source,destination,connection,lookup}.py` (Base classes + Step models + compat maps + `_DLT_CRED_CLASS`) and `backend/dte/store/models.py` (Table classes only, with `sa_column` overrides and timestamps).
- `backend/dte/compiler/ibis_compiler.py` → `packages/dte-sdk/src/dte_sdk/compiler/ibis_compiler.py`.
- `backend/dte/sources/loader.py`, `connection_test.py` → `packages/dte-sdk/src/dte_sdk/sources/`.
- `backend/dte/engine/{base,duckdb_engine}.py` + `backend/dte/engine/writers/` → `packages/dte-sdk/src/dte_sdk/engine/`.
- `backend/dte/secrets/*` → `packages/dte-sdk/src/dte_sdk/secrets/` — **fix**: replace the import-time `_resolver` cache in `dte/secrets/__init__.py:18,49` with lazy resolution + a `set_secret_resolver()` override, so SDK users can configure programmatically.
- `backend/dte/schema/inferrer.py` → `packages/dte-sdk/src/dte_sdk/schema/inferrer.py`.

**Rewrite imports (hard cut) in the app:**
- `backend/dte/api/routes/pipelines.py` — `from dte.models.pipeline import ...` → `from dte_sdk.models import ...`; `from dte.compiler.ibis_compiler import compile_pipeline`; `from dte.engine.duckdb_engine import DuckDBEngine`; `from dte.sources.loader import load_source` → `dte_sdk.*` equivalents. Same treatment for `routes/sources.py`, `routes/destinations.py`, `routes/connections.py`, `routes/schema.py`, `routes/runs.py`.
- `backend/dte/store/postgres.py` — imports the new `dte.store.models` for Table classes; imports Base classes from `dte_sdk.models` for `save()` argument typing.
- `backend/dte/store/base.py` — Protocol argument types point at `dte_sdk.models.*Base`.
- `backend/dte/admin/*` — SQLAdmin model registrations point at `dte.store.models`.
- `backend/tests/fakes.py` and any test importing from `dte.models.pipeline` — rewritten to `dte_sdk.models`.

**Repo root:**
- New root `pyproject.toml` defining a uv workspace with members `backend/` and `packages/dte-sdk/`.
- `backend/pyproject.toml` — remove ibis/dlt/duckdb/pyarrow/s3fs/cryptography from direct deps; add `dte-sdk = { workspace = true }` plus needed extras (`parquet`, `s3`, `gcs`, `azure`, `mongodb`, `fernet`).
- `packages/dte-sdk/pyproject.toml` — new; `[project.dependencies]`: pydantic, ibis-framework[duckdb], dlt, sqlalchemy (needed by `EncryptedJSON` and `sql_database` loader). `[project.optional-dependencies]`:
  - `parquet = ["pyarrow>=15", "fsspec>=2024.6"]`
  - `s3 = ["s3fs>=2024.6"]`
  - `mongodb = ["pymongo"]`
  - `fernet = ["cryptography>=42,<43"]`
  - `sqlmodel = ["sqlmodel>=0.0.22"]`
  - `all = [all of the above]`
- `packages/dte-sdk/README.md` — usage examples: constructing a `SourceBase` in code, calling `load_source` + `compile_pipeline` + `DuckDBEngine.execute` end-to-end in an Airflow `PythonOperator`.

**Delete after the move:**
- `backend/dte/{models,compiler,sources,engine,secrets,schema}/` (all moved out).
- `backend/tests/unit/test_compiler.py`, `test_sources_loader*.py`, `test_secrets*.py` → moved into `packages/dte-sdk/tests/`. Integration tests that touch the store stay in `backend/tests/`.

## Execution order (worktree per phase, per CLAUDE.md)

**Phase 1 — `feature/sdk-workspace-scaffold`** (no logic changes):
1. Add root `pyproject.toml` with `[tool.uv.workspace]`. Create empty `packages/dte-sdk/` with `pyproject.toml`, `src/dte_sdk/__init__.py`, `README.md`, `LICENSE`.
2. `uv sync` at the root; confirm both members resolve.

**Phase 2 — `feature/sdk-move-core`** (mechanical move + import rewrite):
1. Move the six directories listed above into `packages/dte-sdk/src/dte_sdk/`.
2. Split `models/pipeline.py`: Base classes + Step models to `dte_sdk/models/*.py`; Table classes to `backend/dte/store/models.py`.
3. Fix `dte_sdk/secrets/__init__.py`: lazy `get_secret_resolver()` + `set_secret_resolver()`.
4. Rewrite every `from dte.{models,compiler,sources,engine,secrets,schema}...` import in `backend/dte/**` and `backend/tests/**` to `from dte_sdk...`.
5. Move corresponding unit tests into `packages/dte-sdk/tests/`.
6. `cd backend && uv run pytest -m "not integration"` — must pass.
7. `cd packages/dte-sdk && uv run pytest` — must pass.

**Phase 3 — `feature/sdk-public-surface`** (SDK-ergonomic polish, no behavior change):
1. Curate `dte_sdk/__init__.py` re-exports.
2. Write README with Airflow `PythonOperator` example that constructs `SourceBase` + `DestinationBase` + `PipelineBase` in code, calls `load_source` → `compile_pipeline` → `DuckDBEngine().execute`.
3. Add `packages/dte-sdk/examples/airflow_operator.py` sketch (no runtime dep on airflow — pure Python).
4. Full stack smoke: `docker compose up -d --build && docker compose logs -f backend` — pipelines create/trigger end-to-end.

## Verification

- `cd backend && uv run pytest` — full backend suite, including integration when `DATABASE_URL` is set.
- `cd packages/dte-sdk && uv run pytest` — SDK suite.
- `docker compose up -d --build` — full stack boots; `alembic upgrade head` still runs (migrations unchanged); create a pipeline via UI at `:3000`, trigger it, confirm a run reaches `completed`.
- Manual SDK smoke: outside the repo, `pip install -e packages/dte-sdk[all]` in a fresh venv, run the README example against a local JSON file — proves the SDK is truly self-contained.
- `grep -r "from dte\." backend/` should return zero core-module hits (only `dte.api`, `dte.store`, `dte.admin`, `dte.security` remain).

## Out of scope

- Renaming Base classes (`SourceBase` → `Source`) for a prettier SDK API — separate churn, do after the split lands.
- Extracting `StoreProtocol` into the SDK. Airflow users pass model instances directly; they don't need persistence protocols.
- Publishing to PyPI. Set up packaging first; publish in a follow-up.
- Splitting to a separate public repo. Monorepo now; use `git subtree` / `git filter-repo` when ready to open-source.
