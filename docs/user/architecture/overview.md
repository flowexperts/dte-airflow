# Architecture overview

A quick tour of what runs where. For the exhaustive version see the repo's [`ARCHITECTURE.md`](../../../ARCHITECTURE.md).

## Three processes

- **Frontend** — Next.js 16 (App Router, React 19, Tailwind v4). Port 3000. Talks to the backend over HTTP.
- **Backend** — FastAPI. Port 8001. Holds business logic, runs pipelines, exposes REST + `/openapi.json`.
- **Postgres** — pipeline metadata and run history. Port 5432.

## The execution stack

Pipelines run inside the backend process. The stack, top to bottom:

- **dlt** — sources for `mongodb` and `rest_api`. Handles pagination, auth, and initial normalisation.
- **DuckDB** — the query engine. All transforms compile to DuckDB SQL and execute in-process.
- **ibis** — the compiler DSL. Each step in a pipeline maps to an ibis operation; the compiler stitches them into one DuckDB query.

Local files are read by DuckDB directly. S3, GCS, Azure and SFTP files are read and written by DuckDB through the Airflow provider's fsspec filesystem (`ObjectStoragePath`), so the provider does the auth. SQL sources open the database with ibis, using the URL from the provider hook. No dlt in the hot path for these.

## Where credentials live

In Airflow. Connections are Airflow connections (metadata DB, `AIRFLOW_CONN_*` variables or a secrets backend); dte resolves them at run time through `BaseHook.get_connection` and the provider. Sources and destinations reference a connection by id and hold only the "where inside" bits (bucket, table, path). See [Secrets & environment](../self-hosting/secrets.md).

## Storage layout

- **Postgres** — dte's tables (`pipelines`, `sources`, `destinations`, `lookup_tables`, `run_results`, …) are in a `dte` schema of the database `DTE_DATABASE_URL` names: its own database, or Airflow's metadata database. Connections, users and run history stay in Airflow's tables; the api-server reads dag runs through Airflow and merges them with `run_results`.
- **`/data` volume** — files served by the **Local files** connection.
- **In-process** — an ephemeral DuckDB connection per pipeline run. Nothing persists here.

## How a run happens

1. User hits **Trigger** in the UI.
2. Backend creates a `run` row with status `pending`, returns the id immediately.
3. Backend spawns an async task that:
   - Resolves source and destination ids to their configs
   - Loads each source into the run's DuckDB connection (via dlt or a DuckDB extension)
   - Compiles the pipeline steps into one ibis expression
   - Executes it, writes to the destination, records `rows_written`
4. Status flips to `completed` or `failed`. A Postgres trigger stamps `finished_at`.
5. The frontend polls `/api/runs/{id}` every 2 seconds until terminal.

## Where to dig deeper

- Full internals: [`ARCHITECTURE.md`](../../../ARCHITECTURE.md)
- Data flow specifics: [`data-flow.md`](data-flow.md)
- Feature history & rationale: [`plans/`](../../../plans/) — every non-trivial change gets a numbered plan
- Contributor guide: [`CLAUDE.md`](../../../CLAUDE.md)
