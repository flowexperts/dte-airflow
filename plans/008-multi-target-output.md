# Plan 008 — Multi-target Output Writer

## Problem

`DuckDBEngine.execute_to_json` is the only sink today. Users need Postgres, S3 parquet, and other databases (MySQL, Snowflake, BigQuery) as output targets to match the UI Output Mapper (Plan 004).

## Architecture

### OutputTarget model

Add a discriminated union in `dte/models/pipeline.py`:

```python
class JsonFileTarget(BaseModel):
    type: Literal["json_file"]
    path: str

class CsvFileTarget(BaseModel):
    type: Literal["csv_file"]
    path: str

class ParquetS3Target(BaseModel):
    type: Literal["parquet_s3"]
    bucket_url: str
    storage_options: dict = {}

class PostgresTarget(BaseModel):
    type: Literal["postgres"]
    credentials: str          # dsn
    schema_: str              # aliased to "schema"
    table: str
    write_disposition: Literal["replace", "append", "merge"] = "replace"

class SqlDatabaseTarget(BaseModel):
    type: Literal["sql_database"]
    dialect: Literal["mysql", "snowflake", "bigquery"]
    credentials: str
    schema_: str
    table: str
    write_disposition: Literal["replace", "append", "merge"] = "replace"

OutputTarget = Annotated[Union[...], Field(discriminator="type")]
```

`Pipeline` gains `output: OutputTarget | None`. Existing `output_path: str | None` stays for one release, translated at the API/store boundary into `JsonFileTarget(path=output_path)` when `output` is None. Emit a `DeprecationWarning`.

### Writer dispatch

New module `dte/engine/writers/`:

```
writers/
  __init__.py    # write(table, target) -> WriteResult; dispatches by target.type
  json_file.py
  csv_file.py
  parquet_s3.py
  postgres.py
  sql_database.py
```

Each writer signature:

```python
def write(table: ibis.Table, target: OutputTarget, con: ibis.BaseBackend) -> WriteResult
```

`WriteResult = {"rows_written": int, "location": str}`.

`DuckDBEngine` gets a new method `execute(table, target) -> WriteResult` that calls into the dispatcher. `execute_to_json` becomes a wrapper: `execute(table, JsonFileTarget(path=path))`.

### Writer implementations

- **json_file / csv_file** — collect table via ibis then write via `pandas.to_json` / `.to_csv`. Cheap.
- **parquet_s3** — materialise via `table.to_pyarrow()`, write with `pyarrow.parquet.write_table` using `fsspec.open(bucket_url, "wb", **storage_options)`.
- **postgres** — use dlt: build a resource that yields `table.to_pyarrow_batches()`, run `dlt.pipeline(destination=dlt.destinations.postgres(credentials=target.credentials))`. `write_disposition` maps to dlt's.
- **sql_database** — same pattern, destination varies by `dialect` (`dlt.destinations.mysql`, `.snowflake`, `.bigquery`).

### API surface

- `POST /api/pipelines` and `PUT /api/pipelines/{id}` accept `output` in the body.
- `GET /api/runs/{id}` response gains `location` (from the writer's `WriteResult`).

## Tasks

### Task 1 — OutputTarget model + back-compat
- Branch: `feature/output-target-model`
- Add union + discriminator; update `Pipeline`; translation shim; migrate all tests that pass `output_path` to also work with `output`.

### Task 2 — Writer dispatch + json/csv writers
- Branch: `feature/output-writer-dispatch`
- Create `dte/engine/writers/` with json_file + csv_file.
- Refactor `DuckDBEngine.execute_to_json` to delegate.
- Tests: `tests/unit/test_writers_local.py` (tmp_path).

### Task 3 — Postgres writer
- Branch: `feature/output-writer-postgres`
- Integration test uses docker-compose Postgres. Assert row count, then `SELECT COUNT(*)` from the target table.
- Cover all three write dispositions.

### Task 4 — S3 parquet writer
- Branch: `feature/output-writer-s3-parquet`
- Unit test with `moto` or `s3fs` + `memory://` backend.

### Task 5 — SQL database writer (mysql / snowflake / bigquery)
- Branch: `feature/output-writer-sql-database`
- One dialect per PR is fine. Land mysql first (docker-compose can host it); snowflake/bigquery gated behind creds.

## Files changed
- `dte/models/pipeline.py` — union + `Pipeline.output`
- `dte/engine/duckdb_engine.py` — new `execute`; wrapper `execute_to_json`
- `dte/engine/writers/*.py` — new
- `dte/api/routes/runs.py` — expose `location` in response
- `tests/unit/test_writers_*.py`
- `tests/integration/test_writers_postgres.py`, `test_writers_mysql.py`
- `pyproject.toml` — pyarrow, psycopg, s3fs, mysqlclient extras

## What does NOT change
- `dte/compiler/`
- `dte/sources/`
- `dte/store/` (no schema change; `output` is stored inside the pipeline JSON)
