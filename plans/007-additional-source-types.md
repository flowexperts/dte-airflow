# Plan 007 — Additional dlt Source Types

## Problem

`dte/sources/dlt_loader.py:46` raises `NotImplementedError` for every source type except `filesystem`. The UI (Plan 004 Sources page) exposes S3, GCS, MongoDB, Postgres/MySQL, and REST API as options. Backend must accept and load those.

## Architecture

### Dispatch table

`load_source()` becomes:

```python
LOADERS = {
    "filesystem": _load_filesystem,
    "s3": _load_s3,
    "gcs": _load_gcs,
    "sql_database": _load_sql_database,
    "mongodb": _load_mongodb,
    "rest_api": _load_rest_api,
}
```

Each `_load_*(source, con) -> ibis.Table` follows the current pattern: build a dlt resource → run through `dlt.pipeline(destination=dlt.destinations.duckdb(credentials=con.con), dataset_name="dte_sources")` → return `con.table(source.table, database=("memory", "dte_sources"))`.

### Per-source config schemas

New file `dte/sources/config_schemas.py` — a Pydantic model per source type used to validate `DltSource.config` inside each loader. Fail with a helpful error surfaced as HTTP 422 through FastAPI's default exception handling.

| type | required config |
|---|---|
| s3 | `bucket_url`, `aws_access_key_id`, `aws_secret_access_key`, optional `file_glob`, `format` (json/jsonl/csv) |
| gcs | `bucket_url`, `credentials_json`, optional `file_glob`, `format` |
| sql_database | `credentials` (dsn), `schema`, `table` |
| mongodb | `connection_url`, `database`, `collection` |
| rest_api | full dlt `rest_api_source` config dict |

### Credentials resolution

Sources may pass secrets inline OR via env indirection: `{"env": "AWS_SECRET_KEY"}`. A small `resolve_secret(value)` helper in `dlt_loader.py` returns `os.environ[name]` when it sees the env form.

### File organisation

Start inline in `dlt_loader.py`. If the file crosses ~300 lines, split into `dte/sources/loaders/{filesystem,s3,gcs,sql,mongo,rest}.py`; dispatch table stays in `dlt_loader.py`.

## Tasks

### Task 0 — Loader dispatch refactor
- Branch: `feature/source-loader-refactor`
- Extract filesystem loader into `_load_filesystem`, wire dispatch table.
- Add `resolve_secret` helper + tests.
- Pure refactor; no new source types yet. All existing tests must stay green.

### Task 1 — S3 + GCS loaders
- Branch: `feature/source-s3-gcs`
- Use `dlt.sources.filesystem` with `s3://` / `gs://` urls and `storage_options`.
- Test: unit test with mocked `fsspec`, integration behind `AWS_ACCESS_KEY_ID` env marker.

### Task 2 — SQL database loader
- Branch: `feature/source-sql-database`
- `dlt.sources.sql_database.sql_table(credentials, table, schema)`.
- Test: integration against the existing docker-compose Postgres.

### Task 3 — MongoDB loader
- Branch: `feature/source-mongodb`
- `dlt.sources.mongodb.mongodb_collection`.
- Test: integration behind `MONGO_URL` env marker + `mongomock` for unit.

### Task 4 — REST API loader
- Branch: `feature/source-rest-api`
- `dlt.sources.rest_api.rest_api_source(config)`; pass config through after validation.
- Test: unit with `responses` / `httpx_mock`.

## pyproject extras

Add optional extras that pull the right `dlt[...]` sub-deps:
- `dte[s3]` → `dlt[filesystem,s3]`
- `dte[gcs]` → `dlt[filesystem,gs]`
- `dte[sql]` → `dlt[sql_database]` + `psycopg2-binary`
- `dte[mongo]` → `dlt[mongodb]`
- `dte[rest]` → `dlt[rest_api]`

## Files changed
- `dte/sources/dlt_loader.py` — dispatch + secret resolver
- `dte/sources/config_schemas.py` — new
- `dte/sources/loaders/*.py` — only if we split
- `tests/unit/test_dlt_loader.py` — one test per loader (mocked)
- `tests/integration/test_sources_*.py` — new, gated by env markers
- `pyproject.toml` — extras

## What does NOT change
- `dte/compiler/`, `dte/engine/`, `dte/models/pipeline.py` (config stays `dict`)
- `dte/api/routes/schema.py` — still delegates to `load_source`
