# Data flow

What happens inside the Airflow task when a pipeline runs.

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

- filesystem: `CREATE OR REPLACE VIEW … AS SELECT * FROM read_json_auto(…)` (also `read_csv_auto`, `read_parquet`, `read_xlsx`). Format is inferred from the glob's extension; `config["format"]` overrides it.
- s3 / gcs / azure / sftp: `ObjectStoragePath(url, conn_id=…)` returns the provider's fsspec filesystem, registered on the DuckDB connection under a per-connection protocol, so two S3 connections can sit in one pipeline. Then the same `read_*` call runs. Auth is the provider's; dte builds no DuckDB secrets.
- sql_database: ibis connects with the SQLAlchemy URL from the provider hook. When every source is in that one database, the query runs there.
- mongodb / rest_api: dlt `@dlt.resource` / `rest_api_source`, materialised into DuckDB.
- documents: lists files (path, size, modified time) and parses nothing until an **Extract text** step runs.

## Compiling

`dte/compiler/ibis_compiler.py`: `compile_pipeline(pipeline, tables)` walks the ordered steps. Each step reads from and writes back to a **named registry** (`dict[str, ibis.Table]`), keyed by `current_key`.

- Most ops are direct ibis calls (`.filter`, `.mutate`, `.group_by`, `.order_by`, `.select`). **Case** compiles to `ibis.cases`.
- Filter (Advanced), Check (Advanced) and Map · expression are DuckDB-dialect SQL fragments, attached with `table.alias(…).sql(fragment, dialect="duckdb")`. sqlglot transpiles them to the table's backend, so they work against a database source.
- Pivot materialises a temp table, because a dynamic PIVOT can't be a view in DuckDB.
- Join writes its result under `output_id` and updates `current_key`; later steps read from `output_id` explicitly.
- Extract text and Structure fields can't be lazy, because a model call isn't a query. They materialise, map in Python and register the result back. Results are cached by content in `DTE_ARTIFACT_DIR`.

Field references use dot syntax. `_resolve_field()` splits on `.` and traverses struct members. If the head isn't a top-level column, it falls back to the joined `__` name used by dlt-flattened columns from mongodb / rest_api.

## Executing and writing

`dte/engine/duckdb_engine.py` executes the compiled expression and hands the result to a writer under `dte/engine/writers/`. File writers `COPY … TO` the local path or the provider filesystem. Database writers write through the destination's Airflow connection.

## Runs

- Clicking ▶ Run → `POST /dte/api/pipelines/{id}/trigger` → Airflow's REST API triggers the `dte__<id>` DAG with the run's params and the revision id.
- `DtePipelineOperator` runs the pipeline via `dte/airflow/runner.py`; the outcome is upserted into `dte.run_results`, keyed by dag run id.
- Statuses: `pending → running → completed | completed_with_warnings | failed | failed_quality`. Airflow's task state stays the source of truth for whether the task ran.

## Store layer

Every persisted entity (pipeline, source, destination, lookup table) is a pair in `dte/models/pipeline.py`: `XxxBase(SQLModel)` for the API and domain, `Xxx(XxxBase, table=True)` for persistence. Stores live under `dte/store/`; `postgres.py` is the only production backend. Connections aren't stored by dte.

## Further reading

- [`plans/`](https://github.com/flowexperts/dte-airflow/tree/main/plans): numbered feature plans with the reasoning behind each change.
- [`ARCHITECTURE.md`](https://github.com/flowexperts/dte-airflow/blob/main/ARCHITECTURE.md): the contributor reference.
