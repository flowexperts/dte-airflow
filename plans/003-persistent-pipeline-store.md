# Plan 003 — Persistent Pipeline Store

## Problem

All pipeline definitions and run history live in module-level dicts on `dte/api/main.py`. They are lost on restart. There is no way to list pipelines, paginate runs, or query run history.

## Decision

Add Postgres as the persistence layer via SQLAlchemy (async) + Alembic for migrations. Keep the in-memory store as a fallback for tests (swap via dependency injection, not monkey-patching).

## Schema

```sql
CREATE TABLE pipelines (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    definition  JSONB NOT NULL,   -- full Pipeline model_dump()
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id   TEXT NOT NULL REFERENCES pipelines(id),
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending|running|completed|failed
    error         TEXT,
    rows_written  INTEGER,
    started_at    TIMESTAMPTZ DEFAULT now(),
    finished_at   TIMESTAMPTZ
);
```

## Architecture change

### Store abstraction

```python
# dte/store/base.py
class PipelineStore(Protocol):
    async def get(self, id: str) -> dict | None: ...
    async def save(self, pipeline: dict) -> None: ...
    async def list(self, limit: int, offset: int) -> list[dict]: ...

class RunStore(Protocol):
    async def get(self, id: str) -> dict | None: ...
    async def create(self, pipeline_id: str) -> str: ...   # returns run_id
    async def update(self, id: str, **fields) -> None: ...
```

Two implementations:
- `dte/store/memory.py` — current dict-based, used in tests
- `dte/store/postgres.py` — SQLAlchemy async, used in production

### Dependency injection via FastAPI

```python
# dte/api/deps.py
def get_pipeline_store() -> PipelineStore:
    return postgres_store   # or memory_store in tests

# routes use Depends(get_pipeline_store) instead of importing _pipelines
```

Tests override the dependency with the memory store — no Postgres needed in CI.

## Tasks

### Task 1 — Store abstraction + memory implementation
- Branch: `feature/store-abstraction`
- Write tests for memory store first
- Extract current dict logic into `dte/store/memory.py`
- Define Protocol in `dte/store/base.py`
- Wire into API routes via `Depends`

### Task 2 — Postgres implementation + Alembic
- Branch: `feature/postgres-store`
- Add `asyncpg`, `sqlalchemy[asyncio]`, `alembic` to deps
- `dte/store/postgres.py` — async SQLAlchemy implementation
- `alembic/` — initial migration for pipelines + runs tables
- Integration test requires a running Postgres (mark with `pytest.mark.integration`)

### Task 3 — docker-compose
- Branch: `feature/docker-compose`
- `docker-compose.yml` — postgres + dte-api services
- Environment variables: `DATABASE_URL`, `DTE_STORE=postgres|memory`

## Files changed
- `dte/store/` — new directory (base.py, memory.py, postgres.py)
- `dte/api/deps.py` — new
- `dte/api/main.py` — remove module-level dicts
- `dte/api/routes/pipelines.py` — use Depends(get_pipeline_store)
- `dte/api/routes/runs.py` — use Depends(get_run_store)
- `pyproject.toml` — add asyncpg, alembic
- `alembic/` — new
- `docker-compose.yml` — new

## What does NOT change
- `dte/models/pipeline.py`
- `dte/compiler/`
- `dte/engine/`
- `dte/sources/`
- `dte/schema/`
