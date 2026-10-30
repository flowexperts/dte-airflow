# dte — map it once, run it forever

> **Beta.** Interfaces and the `dte` schema may change between releases. Don't run it on production data without backups. Issues welcome; PRs from approved collaborators only (see [CONTRIBUTING](./CONTRIBUTING.md)).

Your domain expert maps the source — once, click by click. Airflow runs it every day after.

dte is a batch data transformation engine that runs as an Airflow 3 app: a visual pipeline builder on top of a typed backend (DuckDB + ibis + dlt) that turns hand-drawn field mappings into reproducible runs. Every pipeline is an Airflow DAG; Airflow owns login, connections, scheduling and run history.

## Quickstart

DTE is an Airflow plugin. Install it into the Airflow 3.3+ you already run, with
Airflow's own constraints file, unmodified:

```bash
AIRFLOW=3.3.2 PY=3.12
curl -fsSLo constraints.txt \
  https://raw.githubusercontent.com/apache/airflow/constraints-$AIRFLOW/constraints-$PY.txt
pip install dte-airflow --constraint constraints.txt
export DTE_DATABASE_URL=postgresql://user:pass@host:5432/dte   
dte db upgrade
```

Then drop the one-line DAG file into your DAGs folder and restart Airflow. Full
steps, extras and environment: [Install into your own Airflow](./docs/user/self-hosting/install-plugin.md).

DTE is under **Plugins ▸ DTE Pipelines** in Airflow's left nav (Transform, Quality
Check); sources, destinations and lookup tables are under **Admin**. Eval and
Visualize pipelines are API-only for now.

1. Use any Airflow connection whose provider is installed (**Admin → Connections**,
   `AIRFLOW_CONN_*` variables or a secrets backend). See [Connections](#connections).
2. Under **Admin**, create a DTE source and destination that use it; then create a pipeline in **DTE Pipelines**.
3. Click **Run**. The run is a dag run of `dte__<pipeline id>`, visible in both UIs.

### No Airflow yet? Try it with Docker Compose

```bash
git clone https://github.com/flowexperts/dte-airflow.git
cd dte-airflow
scripts/bootstrap.sh          # writes .env: fresh secrets + admin password
docker compose up -d --build
```

Open http://localhost:8080 and log in as `admin` with the password `bootstrap.sh`
printed (it's also in `.env`). The stack listens on localhost only and is meant for
local use, not a server.

Ports:

- `8080` — Airflow (UI, REST API, DTE at `/dte`)
- `5432` — postgres (Airflow metadata; DTE tables in the `dte` schema)
- `5433` — demo warehouse

## What's inside

- `backend/` — Python package `dte` (FastAPI API, ibis compiler, DuckDB engine, alembic migrations, tests).
- `frontend/` — React app built by Vite into an Airflow `react_apps` bundle; renders natively inside Airflow at `/plugin/dte` with Airflow's theme.
- `backend/dte/airflow/` — the Airflow integration: plugin, DAG factory, operator, connection adapter.
- `dags/dte_dags.py` — one line that turns every DTE pipeline and schedule into a DAG.
- `plans/` — numbered feature plans documenting the architecture and each shipped change.

## Testing

Three tiers — run only what the change touches:

| Tier | Command | Requires |
|------|---------|----------|
| Unit | `cd backend && uv run pytest` | nothing |
| Integration (Postgres) | `cd backend && uv run pytest tests/integration -m integration` | `DTE_DATABASE_URL` |
| Airflow (stock image + emulators) | `scripts/test-pip-install.sh` | Docker, pnpm, uv |
| Scenario (end-to-end) | `cd backend && uv run pytest tests/scenarios -m scenario -v` | nothing |

### Airflow tier

`scripts/test-pip-install.sh` builds the wheel, installs it into a stock
`apache/airflow` image with Airflow's constraints file unmodified, and runs
pipelines through Airflow, each through its provider: MinIO (S3, amazon),
Azurite (Azure, microsoft-azure), fake-gcs-server (GCS, google), an SFTP server
(sftp) and Postgres (postgres). See
[Install into your own Airflow](./docs/user/self-hosting/install-plugin.md).

## Features

> Legend: **Available** — shipped and working · **Hidden** — implemented, off by default (feature flag) · **Planned** — stubbed or in progress

### Sources

| Source | Type | Status |
|--------|------|--------|
| Local filesystem (JSON, JSONL, CSV, Parquet, Excel) | filesystem | Available |
| AWS S3 (JSON, CSV, Parquet, Excel) | s3 | Available |
| Google Cloud Storage | gcs | Available |
| Azure Blob Storage / ADLS | azure | Available |
| SFTP | sftp | Available |
| PostgreSQL | sql_database | Available |
| MySQL | sql_database | Available |
| SQL Server | sql_database | Available |
| SQLite | sql_database | Available |
| Snowflake | sql_database | Available |
| BigQuery | sql_database | Available |
| MongoDB | mongodb | Available |
| REST API (with pagination) | rest_api | Available |

### Destinations

| Destination | Status |
|-------------|--------|
| JSON, CSV, Excel or Parquet file — local, S3, GCS, Azure or SFTP | Available |
| PostgreSQL | Available |
| SQL database (MySQL, SQL Server, Snowflake, BigQuery) | Available |

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

DTE uses Airflow connections and the provider that owns them does the auth, so IAM
roles, service principals, managed identities and service-account keys work as they
do in your other DAGs. A connection type shows up in DTE only when its provider is
installed; otherwise the picker names the package to install.

| Airflow connection type | Provider | In DTE |
|---|---|---|
| `aws` | amazon (`[s3fs]`) | S3 files |
| `google_cloud_platform`, `gcpbigquery` | google | GCS files; BigQuery (`gcpbigquery`, or extra `dte_type: bigquery`) |
| `wasb`, `adls`, `azure_data_lake` | microsoft-azure | Azure Blob / ADLS files |
| `sftp` | sftp (+ `sshfs`) | SFTP files |
| `postgres`, `mysql`, `mssql`, `sqlite`, `snowflake` | the matching provider | SQL tables (via the hook's SQLAlchemy URL) |
| `mongo` | mongo | MongoDB collections |
| `http` | http | REST APIs |
| `fs` | standard | Local files |

Connections resolve like any task's: secrets backends, `AIRFLOW_CONN_*` variables,
then the metadata DB. **Test** calls the provider's own connection test (follows
Airflow's `[core] test_connection`).

### Runtime & Pipeline Features

| Feature | Status |
|---------|--------|
| Runs execute as Airflow dag runs (`dte__<pipeline>`) | Available |
| Schedules become Airflow cron DAGs | Available |
| Preview / dry run (sample rows, compile-time errors surfaced) | Available |
| Run history per pipeline | Available |
| Run output peek (`GET /api/runs/{id}/output`) | Available |
| Template parameters — `{{params.x}}` in step expressions | Available |
| System variables — `{{today}}` resolves at trigger time | Available |
| Schema inference from an in-flight source body | Available |
| Nested struct fields via dot syntax (`order.amount`) | Available |
| Lookup tables — CRUD + referenced by Map · Lookup step | Available |
| Per-step run timeline events | Available |

### Engines

| Engine | Status |
|--------|--------|
| DuckDB (default) | Available |
| Trino | Hidden — enable with `DTE_TRINO_ENABLED=true` |

### Auth & Access Control

| Feature | Status |
|---------|--------|
| Airflow login and auth manager | Available |
| DTE permissions derived from Airflow DAG access | Available |

## Docs

- **[User guide](./docs/user/README.md)** — start here if you're using the app.
- **[Install into your Airflow](./docs/user/self-hosting/install-plugin.md)** — the pip install.
- **[Try it with Docker Compose](./docs/user/self-hosting/install.md)** — local stack.
- **[Architecture](./docs/user/architecture/overview.md)** — how it fits together.

## Contributing and security

See [CONTRIBUTING.md](./CONTRIBUTING.md), [SECURITY.md](./SECURITY.md) and the [Code of Conduct](./CODE_OF_CONDUCT.md).

## License

Apache-2.0 — see [LICENSE](./LICENSE).

Apache Airflow, Airflow and the Airflow logo are trademarks of the Apache Software Foundation. DTE is an independent project, not affiliated with or endorsed by the ASF.
