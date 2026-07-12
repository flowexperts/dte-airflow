# Plan 011 — Wire `DATABASE_URL` to switch the API store backend

## Problem

`dte/api/deps.py` unconditionally instantiates `MemoryPipelineStore` / `MemoryRunStore`. The `import os` at the top is dead code. `dte/store/postgres.py` exists and is covered by `tests/integration/test_store_postgres.py`, but no code path wires it into the running API.

Consequence just observed: killing `uvicorn` wipes every pipeline — `selectdemo` was lost after a restart even though CLAUDE.md leads the reader to expect Postgres persistence when `DATABASE_URL` is set. The docs describe *intended* behavior that was never implemented.

## Non-goals

- Adding new store methods, indexes, or migrations.
- Runtime toggling between memory and postgres (env is read once at import).
- Changing the request/response shape of any endpoint.

## Architecture

### 1. `dte/store/postgres.py` — take a session factory, not a session

`PostgresPipelineStore.__init__(session)` / `PostgresRunStore.__init__(session)` currently bind one `AsyncSession`. That fits the integration tests (one store per test) but is wrong for the API:

- A store is created per-request via `Depends`; a single long-lived session shared across requests is unsafe.
- `trigger_pipeline` (`dte/api/routes/pipelines.py:97`) hands its `r_store` to `asyncio.create_task(_execute_pipeline(...))` which outlives the request scope; the session it depends on would already be closed.

Change both classes to accept `session_factory: async_sessionmaker[AsyncSession]` and open a fresh `async with session_factory() as s:` scope inside each method. Every method today performs one logical operation and commits at the end, so wrapping is mechanical (rename the `self._session` binding to a locally-scoped `s`). The store instance can then be a long-lived singleton, safe to hold across the background task boundary.

### 2. `dte/api/deps.py` — env-driven backend selection at import

```python
import os
from dte.store.memory import MemoryPipelineStore, MemoryRunStore

_db_url = os.getenv("DATABASE_URL")
if _db_url:
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from dte.store.postgres import PostgresPipelineStore, PostgresRunStore
    _engine = create_async_engine(_db_url)
    _factory = async_sessionmaker(_engine, expire_on_commit=False)
    _pipeline_store = PostgresPipelineStore(_factory)
    _run_store = PostgresRunStore(_factory)
else:
    _pipeline_store = MemoryPipelineStore()
    _run_store = MemoryRunStore()


def get_pipeline_store():
    return _pipeline_store


def get_run_store():
    return _run_store
```

Both stores stay as long-lived singletons — same shape as today. `app.dependency_overrides` in unit tests keeps working unchanged.

### 3. Routes: no change

`dte/api/routes/{pipelines,runs}.py` depend on the Protocols in `dte/store/base.py`. Both concrete stores satisfy them after step 1.

### 4. Docs

`CLAUDE.md` currently says:
> The active backend is wired in `dte/api/deps.py` and injected into routes via FastAPI `Depends()`.

Keep that sentence — it's true after this change. Nothing else to update.

## Task list

Single worktree, single PR — the change is small and its parts must land together.

Branch: `feature/store-backend-switch`

1. Refactor `dte/store/postgres.py` to take `session_factory`. Rewrite each method to open a scoped session.
2. Update `tests/integration/test_store_postgres.py`:
   - Replace `session` fixture with a `session_factory` fixture returning `async_sessionmaker(engine, expire_on_commit=False)`.
   - Update every `PostgresPipelineStore(session)` / `PostgresRunStore(session)` construction.
3. Rewrite `dte/api/deps.py` per section 2.
4. Add `tests/unit/test_deps.py` (memory-mode smoke test — asserts that with `DATABASE_URL` unset the returned stores are the `Memory*` classes). Skip the postgres branch (already covered by integration tests).
5. Verify.

## Files changed

- `dte/store/postgres.py`
- `dte/api/deps.py`
- `tests/integration/test_store_postgres.py`
- `tests/unit/test_deps.py` (new)

## Files deleted

None.

## Verification

1. Memory path (default):
   ```
   pytest tests/unit -x
   uvicorn dte.api.main:app --port 8001 --reload
   # create a pipeline, kill uvicorn, restart — pipeline is gone (expected)
   ```
2. Postgres path (requires local postgres + `alembic upgrade head`):
   ```
   DATABASE_URL=postgresql+asyncpg://... pytest tests/integration/test_store_postgres.py -x
   DATABASE_URL=postgresql+asyncpg://... uvicorn dte.api.main:app --port 8001 --reload
   # create `selectdemo`, kill uvicorn, restart, curl /api/pipelines/selectdemo → 200
   ```
3. Trigger a run under Postgres and confirm the background task writes final status (this exercises the session-factory fix from step 1 across the async-task boundary).
