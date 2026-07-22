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

## Docs

See [`./docs`](./docs) (in progress).

## License

Apache-2.0 — see [LICENSE](./LICENSE).
