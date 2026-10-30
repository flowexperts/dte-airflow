# Data flow

What actually happens inside the Airflow task when a pipeline runs.

## The shape

```
Source config(s) + Airflow connections
    │
    ▼
loader → ibis.Table per source
    │  (local files: DuckDB · object storage: provider fsspec filesystem
    │   SQL: ibis over the provider hook's URL · mongodb / rest_api: dlt)
    ▼
compile_pipeline(steps, tables) → single ibis.Table
    │
    ▼
engine executes → destination writer
    │
    ▼
Output file or table + rows_written → dte.run_results
```

## Loading

`dte/sources/loader.py` has one path per source kind:

- **filesystem**: `CREATE OR REPLACE VIEW … AS SELECT * FROM read_json_auto(…)` (also `read_csv_auto`, `read_parquet`, `read_xlsx`). The format is inferred from the glob's extension, and `config["format"]` overrides it.
- **s3 / gcs / azure / sftp**: `ObjectStoragePath(url, conn_id=…)` returns the Airflow provider's fsspec filesystem, which is registered on the DuckDB connection under a per-connection protocol, so two S3 connections can sit in one pipeline. Then the same `read_*` call runs over it. Auth is entirely the provider's (IAM roles, service principals and service accounts all work), and dte builds no DuckDB secrets.
- **sql_database**: ibis connects to the database using the SQLAlchemy URL from the provider hook. When every source is in that one database, the query runs there.
- **mongodb / rest_api**: dlt `@dlt.resource` / `rest_api_source`, materialised into DuckDB.
- **documents**: lists files (path, size, modified time) and parses nothing until an **Extract text** step runs.

## Compiling

`dte/compiler/ibis_compiler.py`: `compile_pipeline(pipeline, tables)` walks the ordered step list. Each step reads from and writes back to a **named registry** (`dict[str, ibis.Table]`), keyed by `current_key`.

- Most ops are direct ibis calls (`.filter`, `.mutate`, `.group_by`, `.order_by`, `.select`). **Case** compiles to `ibis.cases`.
- **Filter (Advanced)**, **Check (Advanced)** and **Map · expression** are DuckDB-dialect SQL fragments, attached with `table.alias(…).sql(fragment, dialect="duckdb")`. sqlglot transpiles them to the table's own backend, so they work against a database source too.
- **Pivot** materialises a temp table, because a dynamic PIVOT can't be a view in DuckDB.
- **Join** writes its result under `output_id` and updates `current_key`, and later steps read from `output_id` explicitly. This is how multi-source pipelines work.
- **Extract text** and **Structure fields** can't be lazy, because a model call isn't a query. They materialise, map in Python and register the result back, with results cached by content in `DTE_ARTIFACT_DIR`.

Field references use dot syntax. `_resolve_field()` splits on `.` and traverses struct members. If the head isn't a top-level column, it falls back to the joined `__` name used by the dlt-flattened columns from mongodb / rest_api.

## Executing and writing

`dte/engine/duckdb_engine.py` executes the compiled expression and hands the result to a destination writer under `dte/engine/writers/`. File writers `COPY … TO` the local path or the provider filesystem. Database writers write through the destination's Airflow connection.

## Runs

- **▶ Run** → `POST /dte/api/pipelines/{id}/trigger` → Airflow's REST API triggers the `dte__<id>` DAG with the run's params and the revision id.
- `DtePipelineOperator` runs the pipeline via `dte/airflow/runner.py`, and the outcome is upserted into `dte.run_results`, keyed by the dag run id.
- Statuses: `pending → running → completed | completed_with_warnings | failed | failed_quality`. Airflow's own task state stays the source of truth for whether the task ran.

## Store layer

Every persisted entity (pipeline, source, destination, lookup table) is a two-class pair in `dte/models/pipeline.py`: a `XxxBase(SQLModel)` for the API and domain, and a `Xxx(XxxBase, table=True)` for persistence. Stores live under `dte/store/`, and `postgres.py` is the only production backend. Connections aren't stored by dte at all; they come from Airflow.

## Further reading

- [`plans/`](https://github.com/flowexperts/dte-airflow/tree/main/plans): numbered feature plans, each documenting the reasoning behind one shipped change.
- [`ARCHITECTURE.md`](https://github.com/flowexperts/dte-airflow/blob/main/ARCHITECTURE.md): the exhaustive contributor reference.
