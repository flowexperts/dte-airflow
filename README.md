# dte — map it once, run it forever

Your domain expert maps the source — once, click by click. Your orchestrator runs it every day after.

dte is a batch data transformation engine: a visual pipeline builder on top of a typed backend (DuckDB + ibis + dlt) that turns hand-drawn field mappings into reproducible runs.

## Quickstart

```bash
git clone https://github.com/bhavaniravi/dte.git
cd dte
./scripts/bootstrap.sh     # writes .env with fresh secrets
docker compose up -d --build
```

Open http://localhost:3000. The first user to sign up becomes admin.

Ports:

- `3000` — frontend (Next.js)
- `8001` — backend API (FastAPI)
- `5432` — postgres

## What's inside

- `backend/` — Python package `dte` (FastAPI API, ibis compiler, DuckDB engine, alembic migrations, tests).
- `frontend/` — Next.js 16 app (App Router, Tailwind v4, React 19) for the pipeline builder and run UI.
- `packages/dte-sdk/` — standalone Python SDK for defining and running pipelines programmatically.
- `plans/` — numbered feature plans documenting the architecture and each shipped change.

## Testing

Three tiers — run only what the change touches:

| Tier | Command | Requires |
|------|---------|----------|
| Unit | `cd backend && uv run pytest` | nothing |
| Integration (Postgres) | `cd backend && uv run pytest tests/integration -m integration` | `DATABASE_URL` |
| Integration (cloud storage) | `bash scripts/test-cloud-storage.sh` | Docker |
| Scenario (end-to-end) | `cd backend && uv run pytest tests/scenarios -m scenario -v` | nothing |

### Cloud storage integration tests

`scripts/test-cloud-storage.sh` spins up MinIO, Azurite, and fake-gcs-server via Docker, seeds fixture data, runs the suite, and tears down on exit.

**Latest run — 11 passed, 0 skipped (2026-08-04):**

| Test | Emulator | What it verifies |
|------|----------|-----------------|
| `TestS3Loader::test_reads_json_file` | MinIO | S3 JSON read, 20 rows |
| `TestS3Loader::test_reads_parquet_file` | MinIO | S3 Parquet read via DuckDB httpfs |
| `TestS3Loader::test_filter_expression` | MinIO | S3 source filter pushdown |
| `TestAzureLoader::test_reads_json_file` | Azurite | Azure Blob JSON read, 20 rows |
| `TestAzureLoader::test_aggregate` | Azurite | Azure Blob SUM aggregate |
| `TestGCSLoader::test_reads_json_file` | fake-gcs-server | GCS JSON read via TYPE gcs + ENDPOINT override |
| `TestGCSLoader::test_filter_expression` | fake-gcs-server | GCS source filter |
| `test_pipeline_s3_source_to_local_json` | MinIO → local | Full pipeline: S3 source → filter → json_file |
| `test_pipeline_local_source_to_s3_parquet` | local → MinIO | Full pipeline: filesystem source → filter → parquet_s3 |
| `test_pipeline_azure_source_to_local_json` | Azurite → local | Full pipeline: Azure source → rename → json_file |
| `test_pipeline_gcs_source_to_local_json` | fake-gcs-server → local | Full pipeline: GCS source → sort → json_file |

## Features

> Legend: **Available** — shipped and working · **Hidden** — implemented, off by default (feature flag) · **Planned** — stubbed or in progress

### Sources

| Source | Type | Status |
|--------|------|--------|
| Local filesystem (JSON, JSONL, CSV, Parquet, Excel) | filesystem | Available |
| AWS S3 (JSON, CSV, Parquet) | s3 | Available |
| Google Cloud Storage — HMAC auth only | gcs | Available |
| Azure Blob Storage | azure | Available |
| PostgreSQL | sql_database | Available |
| MySQL | sql_database | Available |
| SQLite | sql_database | Available |
| Snowflake | sql_database | Available |
| BigQuery | sql_database | Available |
| MongoDB | mongodb | Available |
| REST API (with pagination) | rest_api | Available |

### Destinations

| Destination | Status |
|-------------|--------|
| JSON file | Available |
| CSV file | Available |
| Excel file | Available |
| Parquet on S3 | Available |
| PostgreSQL | Available |
| SQL database (MySQL, Snowflake, BigQuery) | Available |

### Transform Steps

| Step | Description | Status |
|------|-------------|--------|
| Filter — Basic | GUI-built SQL `WHERE` (no injection surface) | Available |
| Filter — Advanced | Raw SQL expression | Available |
| Rename | Rename one or more columns | Available |
| Retype | Cast a column to a target type | Available |
| Map · Lookup | Join a saved lookup table to replace values | Available |
| Map · Expression | Derive a new column from a raw SQL expression | Available |
| Map · Calculation | Derive a column from a typed formula (same backend as expression) | Available |
| Sort | Order rows by one or more fields, asc or desc | Available |
| Aggregate | Group-by with SUM / COUNT / AVG / MIN / MAX | Available |
| Join | Inner / left / right / outer join across two sources | Available |
| Pivot | Reshape rows to columns (DuckDB PIVOT) | Available |
| Select / Drop fields | Keep or drop a set of columns, with optional aliases | Available |
| Check | Data-quality assertion — fail or warn when the expression is false | Available |
| Profile columns | Per-column null count, distinct count, min/max stats | Available |

### Connections

| Connection type | Status |
|----------------|--------|
| Local filesystem (no credentials) | Available |
| AWS (access key + secret) | Available |
| GCS (HMAC key) | Available |
| Azure (connection string or account key) | Available |
| PostgreSQL | Available |
| MySQL | Available |
| SQLite | Available |
| Snowflake | Available |
| BigQuery | Available |
| MongoDB | Available |
| REST API | Available |
| Connectivity test (`POST /api/connections/{id}/test`) | Available |
| Credentials encrypted at rest (Fernet) | Available |

### Runtime & Pipeline Features

| Feature | Status |
|---------|--------|
| Async pipeline execution — trigger returns immediately, caller polls | Available |
| Preview / dry run (sample rows, compile-time errors surfaced) | Available |
| Run history per pipeline | Available |
| Run output peek (`GET /api/runs/{id}/output`) | Available |
| Template parameters — `{{params.x}}` in step expressions | Available |
| System variables — `{{today}}` resolves at trigger time | Available |
| Schema inference from an in-flight source body | Available |
| Nested struct fields via dot syntax (`order.amount`) | Available |
| Lookup tables — CRUD + referenced by Map · Lookup step | Available |
| Per-step run timeline events | Planned — frontend stub in place, backend not recording yet |

### Engines

| Engine | Status |
|--------|--------|
| DuckDB (default) | Available |
| Trino | Hidden — enable with `DTE_TRINO_ENABLED=true` |

### Auth & Access Control

| Feature | Status |
|---------|--------|
| Email/password login — first user becomes admin | Available |
| Role-based permissions | Available |

### Integrations & SDK

| Feature | Status |
|---------|--------|
| Python SDK (`dte-sdk`) — define and run pipelines as Python objects | Available |
| Orchestrator-ready SDK (Airflow, Prefect, Dagster operators) | Available |

## Docs

- **[User guide](./docs/user/README.md)** — start here if you're using the app.
- **[Self-hosting](./docs/user/self-hosting/install.md)** — running your own instance.
- **[Architecture](./docs/user/architecture/overview.md)** — how it fits together.

## License

Apache-2.0 — see [LICENSE](./LICENSE).
