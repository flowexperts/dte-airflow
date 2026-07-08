# Plan 009 — Standalone Sources Resource

## Problem

Sources currently live inline inside `Pipeline.sources`. The UI's Sources page (`/sources` in Plan 004) assumes sources are a first-class resource: creatable, listable, editable, and referenceable across pipelines. Without CRUD on sources there is no way to reuse a source config or preview its schema by id.

## Architecture

### Source model

New file `dte/models/source.py`:

```python
class Source(BaseModel):
    id: str                    # uuid
    name: str
    source_type: str           # filesystem, s3, sql_database, ...
    config: dict
    table: str                 # ibis/duckdb table name
    created_at: datetime
```

`DltSource` (in `dte/models/pipeline.py`) is unchanged. A `Source` can be projected to a `DltSource` for the loader.

### Pipeline source reference

`Pipeline.sources` becomes `list[DltSource | SourceRef]` where:

```python
class SourceRef(BaseModel):
    source_ref: str            # source id
```

At compile time, `dte/compiler/ibis_compiler.py` resolves refs against a `SourceStore` (passed in) before calling `dlt_loader.load_source`. Inline `DltSource` continues to work.

### SourceStore

Add to `dte/store/base.py`:

```python
class SourceStore(Protocol):
    async def create(self, source: Source) -> Source: ...
    async def get(self, source_id: str) -> Source | None: ...
    async def list(self) -> list[Source]: ...
    async def update(self, source: Source) -> Source: ...
    async def delete(self, source_id: str) -> bool: ...
```

Plus `PipelineStore.list_referencing_source(source_id) -> list[Pipeline]` used by delete guard.

Implementations:
- `dte/store/memory.py` — dict.
- `dte/store/postgres.py` — SQLAlchemy async; new table via alembic:

```sql
CREATE TABLE sources (
  id uuid PRIMARY KEY,
  name text NOT NULL,
  source_type text NOT NULL,
  config jsonb NOT NULL,
  table_name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
```

DI in `dte/api/deps.py` mirrors existing pattern (`get_source_store`).

### Routes

New `dte/api/routes/sources.py`:

```
POST   /api/sources               create
GET    /api/sources               list
GET    /api/sources/{id}          get
PUT    /api/sources/{id}          update
DELETE /api/sources/{id}          delete (409 if referenced by any pipeline)
GET    /api/sources/{id}/schema   → { "fields": [{"name","type"}] }
```

The `/schema` endpoint reuses the logic already in `dte/api/routes/schema.py:10-19` — extract it into `dte/schema/dlt_schema.py::infer_from_dlt_source(source) -> list[Field]` and both routes call it.

Register the new router in `dte/api/main.py`.

## Tasks

### Task 1 — Source model + store
- Branch: `feature/source-model-store`
- New model, protocol, memory + postgres impls, alembic migration.
- Tests: `tests/unit/test_store_sources.py` (memory) + gated postgres integration test.

### Task 2 — Source routes (excluding schema)
- Branch: `feature/source-routes`
- POST / GET / GET-by-id / PUT / DELETE.
- Tests: `tests/unit/test_api_sources.py`.

### Task 3 — Source schema endpoint reuse
- Branch: `feature/source-schema-reuse`
- Extract shared inferrer into `dte/schema/dlt_schema.py`.
- Wire `GET /api/sources/{id}/schema` and refactor `POST /api/schema/infer` to reuse it.
- Tests: extend `test_api_schema.py`.

### Task 4 — SourceRef in pipelines
- Branch: `feature/source-ref-in-pipeline`
- Extend `Pipeline.sources` union, resolver in compiler, DI plumbs `SourceStore` into the executor / preview flow.
- Tests: pipeline with a `SourceRef` produces the same compiled table as the inline equivalent.

### Task 5 — Delete guard
- Branch: `feature/source-delete-guard`
- `PipelineStore.list_referencing_source` + 409 response.
- Tests: create pipeline referencing source → DELETE returns 409 with list of pipeline ids.

## Files changed
- `dte/models/source.py` — new
- `dte/models/pipeline.py` — `SourceRef` in union
- `dte/store/base.py`, `memory.py`, `postgres.py`
- `alembic/versions/xxxx_sources_table.py` — new
- `dte/api/deps.py`
- `dte/api/routes/sources.py` — new
- `dte/api/routes/schema.py` — refactor to shared inferrer
- `dte/schema/dlt_schema.py` — new
- `dte/compiler/ibis_compiler.py` — ref resolution
- `dte/api/main.py` — register router
- `tests/unit/test_api_sources.py`, `test_store_sources.py`, extend `test_api_schema.py`

## What does NOT change
- `dte/engine/` — unaffected
- `dte/sources/dlt_loader.py` — still loads a `DltSource`; refs are resolved to `DltSource` before hitting the loader
