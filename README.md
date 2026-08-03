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

## Docs

- **[User guide](./docs/user/README.md)** — start here if you're using the app.
- **[Self-hosting](./docs/user/self-hosting/install.md)** — running your own instance.
- **[Architecture](./docs/user/architecture/overview.md)** — how it fits together.

## License

Apache-2.0 — see [LICENSE](./LICENSE).
