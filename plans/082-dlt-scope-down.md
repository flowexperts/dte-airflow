# 082 — Shrink dlt to where it earns its keep

## Problem

dlt is a core dependency on four paths: the Mongo and REST API sources, the
Postgres writer, and the mysql/mssql/snowflake/bigquery writer. dlt is built to
load into datasets *it* owns — infer the schema, normalise identifiers, keep
state in `_dlt_*` tables. Our writers put rows into tables the *user* owns,
under column names the user declared. That mismatch has already cost us:

- **Silent wrong-column writes** (backend/CLAUDE.md, "dlt-backed writers must
  not normalise identifiers"). Fixed with `naming_convention="direct"` plus a
  throwaway `pipelines_dir` — two settings that exist only to switch off what
  dlt is for.
- **`_dlt_*` tables in user databases**, and destinations written under the
  old convention fail with `TableIdentifiersFrozen` until someone drops them.
- **`merge` probably appends.** `PostgresTarget` / `SqlDatabaseTarget` offer
  `write_disposition="merge"` but carry no key, and the writers pass none to
  `@dlt.resource`. dlt documents merge-without-key as append. Unverified.
- **Writers materialise the whole result** via `table.to_pyarrow()` before
  dlt sees a row. File targets stream through DuckDB `COPY` (`_copy.py`); DB
  targets OOM on results that fit fine as Parquet.
- **Trino pulls its result out of the cluster.** `TrinoEngine.execute` uses
  the same writers, so a Trino run drags every row into one worker — the exact
  thing `EnrichmentNotSupportedOnBackend` refuses to do. Trino is also the
  last backend configured from env vars (`DTE_TRINO_*`) instead of an Airflow
  connection.

Arrow is not in question: it is how ibis, DuckDB and dlt hand data to each
other. Only the full-materialisation call is a bug.

## Decision

| Path | After this plan | Why |
|---|---|---|
| REST API source | dlt (unchanged) | Pagination, auth, data selectors are real work. |
| Mongo source | `MongoHook` + Arrow | dlt is only a slow row-by-row pipe here. |
| Postgres, MySQL writers | DuckDB `ATTACH … (TYPE postgres|mysql)` | Same mechanism the sources already use; streams; no `_dlt_*` tables; no renaming. |
| Snowflake, BigQuery, MSSQL writers | dlt, batch-streamed, optional extras | DuckDB can't attach these. Move to the provider's bulk loader only when a user hits an auth case a URL can't carry. |
| Trino engine writes | In-cluster `INSERT … SELECT` / CTAS, else refuse | Never pull the result out of the cluster. |

End state: dlt leaves core `dependencies` and lives only in the extras that
need it (`rest-api`, `snowflake-writer`, `bigquery-writer`, `mssql`).

Not doing: removing dlt entirely (own REST client + merge for five dialects).

## Tasks

Each step is its own worktree and branch, merged before the next starts.
TDD: the failing test lands first in every step.

### 1. Merge disposition — `feature/082-merge-key`

- Test: `merge` twice with overlapping rows against Postgres (integration)
  → assert no duplicates. Expected to fail (appends).
- If it fails, pick one and implement it:
  - **a.** add `merge_key: list[str]` to both targets, required when
    `write_disposition == "merge"` (model validator), passed through as the
    resource's `primary_key`; or
  - **b.** remove `merge` from the `Literal` and migrate saved destinations
    with `merge` to `append` (Alembic data migration), surfacing the change.
  - Default to **a**; the UI already offers merge, so users expect it.
- Frontend: destination form shows a key-columns picker when merge is chosen
  (reuse the destination schema endpoint from plan 057).

### 2. Postgres + MySQL writers on DuckDB ATTACH — `feature/082-attach-writers`

- Tests: replace / append / merge round-trips against Postgres and MySQL
  (integration), plus mixed-case column names (`CustomerID`) landing in the
  declared column — the regression the dlt naming fix guards today.
- New `writers/attach.py`: `ATTACH` the URL read-write, then
  `CREATE OR REPLACE TABLE` / `INSERT INTO … SELECT` from the ibis expression,
  so rows stream inside DuckDB. Reuse the scheme/URL handling from the source
  side (`dte/sources/loader.py` sql_database path) instead of re-deriving it.
- Merge: DuckDB upsert into an attached table if the extension supports it
  (verify first); otherwise stage into a temp table on the target and run
  `INSERT … ON CONFLICT` (Postgres) / `ON DUPLICATE KEY UPDATE` (MySQL) there.
- `postgres.py` deleted; `mysql` removed from `sql_database.py`'s factory.
- Existing `_dlt_*` tables are left alone (harmless); note in release notes.

### 3. Mongo source on MongoHook + Arrow — `feature/082-mongo-hook`

- Tests: nested documents arrive as STRUCT columns; `_id` dropped; filter
  honoured.
- `_load_mongo`: reuse `dte/sources/pools/mongo.py` for the client, build
  `pyarrow.Table.from_pylist` in batches, register on DuckDB.
- Field refs change from `a__b` to `a.b`: run
  `scripts/migrate_field_refs.py` over saved pipelines; update the
  `_resolve_field` fallback note in backend/CLAUDE.md.

### 4. Stream the remaining dlt writers, move dlt to extras — `feature/082-dlt-extras`

- Test: writer resource yields `RecordBatch`es, never calls `to_pyarrow()`
  (intercept the destination factory as `test_writer_naming_convention.py`
  does).
- `sql_database.py`: `yield from table.to_pyarrow_batches()`; `rows_written`
  summed from batches.
- `pyproject.toml`: `dlt[duckdb]` out of core deps; new `rest-api` extra;
  `mysql-writer` / `postgres-writer` extras dropped. `Dockerfile.airflow`
  installs `rest-api`. Missing extra → clear error at save time, not at run.
- Respect Airflow constraints (pyarrow pin) — never loosen them.

### 5. Trino writes in-cluster — `feature/082-trino-writes`

Lowest priority: Trino is experimental.

- Tests first, to settle two unknowns: what `_copy.py` does when handed a
  Trino connection, and whether ibis-trino's `insert(name, expr)` /
  `create_table(name, obj=expr)` stay server-side for replace and append.
- `TrinoEngine.execute`: targets reachable as a Trino catalog →
  `INSERT … SELECT` / CTAS; anything else → `WriteNotSupportedOnBackend`
  (same shape as `EnrichmentNotSupportedOnBackend`).
- Connection from `TrinoHook` (`apache-airflow-providers-trino`, new `trino`
  extra entry); drop `DTE_TRINO_*` env vars.

## Files

Changed: `backend/dte/models/pipeline.py`, `backend/dte/sources/loader.py`,
`backend/dte/engine/writers/__init__.py`, `backend/dte/engine/writers/sql_database.py`,
`backend/dte/engine/trino_engine.py`, `backend/pyproject.toml`,
`Dockerfile.airflow`, `backend/CLAUDE.md`, frontend destination form,
`docs/user/architecture/*`, `site/src/lib/oss.ts` (dlt credit narrows).

New: `backend/dte/engine/writers/attach.py`, an Alembic migration if step 1
picks option b, tests per step.

Deleted: `backend/dte/engine/writers/postgres.py`,
`backend/dte/sources/dlt_loader.py` (deprecated shim, past its release).

## Open questions

- Does DuckDB's postgres/mysql extension support upsert into an attached
  table? Decides how much SQL step 2's merge needs.
- Snowflake key-pair / OAuth via `SnowflakeHook.sqlalchemy_url` — does it
  survive into the URL dlt receives? Not blocking; decides when step 4's
  "move to provider bulk loader" becomes necessary.
