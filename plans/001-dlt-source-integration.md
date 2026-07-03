# Plan 001 — Replace Custom Connectors with dlt

## Problem

The current `dte/connectors/` module is a hand-rolled abstraction for JSON files and CSVs. It can't handle S3, MongoDB, GCS, REST APIs, or any other real-world source without writing individual connector classes. dlt (dlthub) already solves this — it ships sources for every major system and handles auth, pagination, schema inference, and incremental loading.

## Decision

Remove `dte/connectors/`. Use dlt as the universal extraction layer. dlt loads source data into an in-process DuckDB connection; the DTE compiler then applies transforms on the resulting tables.

## Architecture after this change

```
Pipeline.source (dlt config)
    ↓
dlt pipeline.run(source → duckdb destination)
    ↓
DuckDBEngine.con  ← dlt-populated tables registered here
    ↓
compile_pipeline() → ibis.Table
    ↓
execute_to_json() / execute_to_db()
```

The `Pipeline.sources` field changes from a typed connector config to a dlt source descriptor: a `source_type` (dlt source name) plus arbitrary `config` dict that dlt passes to the source.

## Pipeline spec change

Before:
```json
{
  "sources": [{"id": "s1", "type": "json_file", "path": "/tmp/data.json"}]
}
```

After:
```json
{
  "sources": [{
    "id": "s1",
    "source_type": "filesystem",
    "config": {"bucket_url": "s3://my-bucket/data/", "file_glob": "*.json"},
    "table": "data"
  }]
}
```

For local files in tests, use dlt's `filesystem` source with a local path.

## Tasks

### Task 1 — Update dependencies
- Add `dlt[duckdb]` to `pyproject.toml`
- Remove `sqlalchemy` (was only needed for DB introspection in connectors)
- Branch: `feature/dlt-deps`

### Task 2 — New Pipeline source model
- Replace `JsonFileSource`, `CsvFileSource`, `PostgresSource` with a single `DltSource` model
- Fields: `id: str`, `source_type: str`, `config: dict`, `table: str`
- `Pipeline.sources: list[DltSource]`
- Update `test_pipeline_spec.py` first
- Branch: `feature/dlt-source-model`

### Task 3 — dlt loader module
- Create `dte/sources/dlt_loader.py`
- `load_source(source: DltSource, con: duckdb.DuckDBPyConnection) -> ibis.Table`
- Internally: create a dlt pipeline with duckdb destination pointing at the existing `con`
- Return `con.table(source.table)` as ibis.Table
- Write `tests/unit/test_dlt_loader.py` first (use dlt `filesystem` source with `tmp_path`)
- Branch: `feature/dlt-loader`

### Task 4 — Remove connectors module
- Delete `dte/connectors/`
- Update `DuckDBEngine`: remove `load_json`, `load_csv` methods; accept pre-loaded ibis.Table dict
- Update `dte/api/routes/pipelines.py` trigger handler to call `load_source` per source
- Branch: `feature/remove-connectors`

### Task 5 — Update integration tests
- Replace direct `engine.load_json()` calls with `dlt_loader.load_source()`
- Use dlt `filesystem` source pointing at `tmp_path` for all file-based fixtures
- Branch: `feature/integration-tests-dlt`

## Files changed
- `pyproject.toml` — add dlt[duckdb]
- `dte/models/pipeline.py` — replace source types with DltSource
- `dte/sources/dlt_loader.py` — new
- `dte/engine/duckdb_engine.py` — remove load_* methods
- `dte/api/routes/pipelines.py` — use dlt_loader in trigger
- `dte/connectors/` — deleted
- `tests/unit/test_pipeline_spec.py` — updated
- `tests/unit/test_dlt_loader.py` — new
- `tests/integration/test_execution.py` — updated

## What does NOT change
- `dte/compiler/ibis_compiler.py` — no change, still consumes ibis.Table
- `dte/schema/inferrer.py` — no change for now (schema inference will later delegate to dlt's schema)
- `dte/api/routes/runs.py` — no change
- All step types in `pipeline.py` — no change
