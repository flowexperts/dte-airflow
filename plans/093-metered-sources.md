# 093 — Metered sources: sample previews, estimates, caps, partition hints

Branch: `feature/093-metered-sources` (worktree `worktrees/093-metered-sources`).
(092 was taken by file-mode lineage.)

## Problem

On a warehouse, `LIMIT` does not make a query cheap. BigQuery bills the
columns it scans; Snowflake bills warehouse time. Today every builder preview,
step-schema call and schema inference against a `sql_database` source is
pushed down live. Measured: a `bq_smoke` preview on `samples.shakespeare`
(6.4 MB) bills 10 MB per query (BigQuery's minimum), two billed queries per
preview, and the builder fires preview on every edit. Pointed at
`bigquery-public-data.pypi.file_downloads` (1.44 PB, DAY-partitioned on
`timestamp`, no required partition filter) one unfiltered preview could bill
~$9,000.

## Scope

DTE supports two warehouse source kinds today (`ConnectionType`,
`SOURCE_CONNECTION_COMPAT["sql_database"]`): **bigquery** and **snowflake**.
Those two are "metered". Databricks/Trino/Athena/ClickHouse/Redshift have no
source mapping, so nothing is built for them; the fallback paths below cover
any engine added later.

## Architecture change

One new module, `dte/sources/metered.py`: `METERED`, `is_metered`,
`fetch_sample`, `partition_columns`, `estimate_bytes`, `cap_message`,
`QueryCapExceeded`. Everything engine-specific lives there.

1. **Sample previews.** `sample.load_interactive` gets a third class beside
   eager/lazy: a metered `sql_database` source is fetched once per
   (source, connection, table) with the engine's cheapest primitive and cached
   as parquet next to the eager samples (same key, TTL, lock), plus a sidecar
   JSON holding the partition columns. Interactive paths then run in DuckDB.
   - BigQuery: `client.list_rows(table, max_results=N)` (tabledata.list, free).
   - Snowflake: `TABLESAMPLE SYSTEM (1) LIMIT N`, falling back to `LIMIT N`
     when the block sample comes back short (small table, so cheap).
   - Anything else: `LIMIT N`.
   - `_load_compile(live=True)` bypasses the sample; `GET .../preview` and
     `POST .../dry-run` take `?live=true`. Responses carry
     `samples: [{alias, rows, taken_at}]`.
   - `DELETE /api/sources/{id}/sample?table=` drops the cached sample (Refresh).
   - Runs (`runner.run_pipeline`) still call `load_source` directly: live.
2. **Estimate, then confirm.** `estimate_bytes(expr)`: BigQuery dry run
   (`dry_run=True`, free, exact); Snowflake `EXPLAIN USING JSON` →
   `GlobalStats.bytesAssigned`. A pipeline estimate compiles against the live
   backends (metadata only) and dry-runs the compiled query when it lives on
   the warehouse, else each metered input table in full. Pipelines with eager
   steps (extract/structure/pivot/check/profile) skip compile and price the
   full input tables — compiling those would execute them.
   - `POST /api/pipelines/estimate` (unsaved body; the builder's "Preview on
     live data" confirm).
   - `POST /api/pipelines/{id}/trigger` gains `confirm` (the sweep shape): a
     metered pipeline without `confirm` returns
     `{estimate, enqueued: false}` and starts nothing.
   - Price: BigQuery on-demand `$6.25/TiB`, a constant. Snowflake: bytes only,
     `est_cost_usd: null` — it bills time, not bytes.
3. **Hard cap on the connection.** `from_airflow` copies two extras into the
   credentials of a metered connection: `dte_max_bytes_billed` (BigQuery
   `maximum_bytes_billed` through the client's `default_query_job_config`,
   `ibis.bigquery.connect(client=...)`) and `dte_statement_timeout_seconds`
   (Snowflake `STATEMENT_TIMEOUT_IN_SECONDS` session parameter). Applied in the
   `backend_registry` openers, so preview, runs and introspection all get it.
   A cap hit becomes `QueryCapExceeded` with "needs X, cap is Y" (runner phase
   and preview error), not a driver traceback. Snowflake has no bytes cap;
   ClickHouse/others are out of scope (no source kind).
4. **Partition hint.** `partition_columns` (BigQuery `time_partitioning.field`
   or `_PARTITIONTIME`, `range_partitioning.field`; Snowflake none) is stored
   with the sample and returned on the schema response
   (`InferSchemaResponse.partition_columns`). The builder warns
   "No filter on `timestamp` — this run scans the whole table." when no
   filter step mentions it.

Also fixed on the way: `_open_snowflake` passed the URL positionally to
`ibis.snowflake.connect` (it lands in `create_object_udfs`); it now uses
`ibis.connect(url, ...)`. Carries the uncommitted `_open_bigquery`
`dataset_id=""` fix from `dte-airflow`.

## Tasks (all on `feature/093-metered-sources`)

1. Tests first: `tests/unit/test_metered.py` (sample fetch per engine,
   load_interactive caches metered, partition columns, estimate, cap message,
   from_airflow caps), extra cases in `test_backend_registry.py` (caps reach
   the client / session), `tests/scenarios/test_metered_sources.py` (preview
   reads sample, live bypasses it, trigger needs confirm, schema carries
   partition columns) with fakes — never real BigQuery.
2. `dte/sources/metered.py`, `sample.py`, `backend_registry.py`,
   `airflow/connections.py`, `airflow/runner.py`.
3. API: `routes/pipelines.py` (live, samples, estimate, trigger confirm),
   `routes/schema.py` (partition_columns), `routes/sources.py` (DELETE sample).
4. Frontend: regen `api-types.ts`; `api.ts`, `pipeline-preview.tsx` (sample
   label, Refresh, Preview on live data with estimate confirm),
   `pipeline/trigger.tsx` (estimate confirm), `schema-context.tsx` +
   partition hint in the steps panels.
5. Docs: `backend/CLAUDE.md`, `dte/api/CLAUDE.md`, `dte/sources/CLAUDE.md`.

## Files

New: `backend/dte/sources/metered.py`, `backend/tests/unit/test_metered.py`,
`backend/tests/scenarios/test_metered_sources.py`,
`frontend/src/components/builder/partition-hint.tsx`.
Changed: `backend/dte/sources/sample.py`, `backend/dte/engine/backend_registry.py`,
`backend/dte/airflow/connections.py`, `backend/dte/airflow/runner.py`,
`backend/dte/api/routes/{pipelines,schema,sources}.py`, the three CLAUDE.md
files, `frontend/src/lib/{api,api-types}.ts`,
`frontend/src/components/{pipeline-preview.tsx,pipeline/trigger.tsx,builder/schema-context.tsx}`,
the two steps panels.
Deleted: none.
