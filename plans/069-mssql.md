# 069 — Microsoft SQL Server (source + destination)

## Problem

DTE reads postgres/mysql/sqlite/snowflake/bigquery and writes
postgres/mysql/snowflake/bigquery. SQL Server is the most common database in
the enterprise shops we sell to, and none of it is reachable.

## Architecture change

None. SQL Server rides the existing seams the same way MySQL does:

```
Connection(type=mssql, credentials={"url": "mssql://user:pw@host:1433/db"})
  ├─ source:      BackendRegistry → ibis.mssql.connect(...)  (pushdown, like mysql)
  ├─ destination: SqlDatabaseTarget(dialect="mssql") → dlt.destinations.mssql
  └─ probe:       SQLAlchemy  mssql+pyodbc  SELECT 1
```

- **One driver for everything: pyodbc + Microsoft ODBC Driver 18.** ibis's
  mssql backend only speaks pyodbc, and dlt's `mssql` destination does too,
  so pymssql would only add a second driver. The ODBC driver is a system
  package, installed in `Dockerfile.airflow` from Microsoft's apt repo.
- **URL in, kwargs out.** Users save `mssql://user:pw@host:port/db` (the same
  shape as every other SQL connection). `_open_mssql` splits it for ibis;
  the writer and probe rewrite it to `mssql+pyodbc://…?driver=ODBC+Driver+18+for+SQL+Server`.
- **TLS**: ODBC 18 encrypts by default and rejects self-signed certs. Query
  params on the saved URL (`?TrustServerCertificate=yes`) pass through to
  ibis and SQLAlchemy untouched — no new UI field.
- Raw-SQL steps: sqlglot transpiles DuckDB → `tsql`. Not measured for
  divergences yet; `dialect_notes` gets no entries until it is.

## Tasks (branch `feature/mssql`)

1. `ConnectionType`, `_DLT_CRED_CLASS`, `SOURCE_/DESTINATION_CONNECTION_COMPAT`,
   `SqlDatabaseTarget.dialect`, `EngineChoice`/`EngineName`,
   `ENGINE_READ/WRITE_SUPPORT` gain `mssql`.
2. `backend_registry._open_mssql` + `_OPENERS["mssql"]`.
3. `writers/sql_database.py` — `mssql` → `dlt.destinations.mssql`.
4. `connection_test._probe_mssql` (URL rewrite, then `_probe_sql_url`).
5. `engine/registry.py` pushdown set; `loader._fabricate_legacy_connection` scheme.
6. `pyproject.toml` extras `mssql` = `ibis-framework[mssql]`, `dlt[mssql]`, `pyodbc`.
7. `Dockerfile.airflow` — msodbcsql18 + `[mssql]` extra.
7b. `dte/airflow/connections.py` — Airflow `mssql` conn type → DTE, extras as ODBC query params.
8. Frontend: `ConnectionType`, `EngineChoice`, sql_database dialect lists.
9. Tests: unit tests for the opener URL split, the writer factory, the probe
   rewrite, compat maps.

## Files

- `backend/dte/models/pipeline.py`
- `backend/dte/engine/backend_registry.py`, `engine/registry.py`, `engine/writers/sql_database.py`
- `backend/dte/sources/connection_test.py`, `sources/loader.py`
- `backend/pyproject.toml`, `Dockerfile.airflow`
- `frontend/src/lib/api.ts`, `components/builder/sources/types.ts`, `components/destination-form.tsx`
- `backend/tests/unit/test_mssql.py` (new)

## Out of scope

- Trino federation over SQL Server (add `mssql` to the trino row when a
  catalog for it is configured somewhere).
- Windows/AAD auth — URL query params can carry `Authentication=…` already;
  a form for it waits for someone to ask.
