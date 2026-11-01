# Secrets & environment

dte stores no credentials. Connections are Airflow connections, kept in the metadata database (Fernet-encrypted), `AIRFLOW_CONN_*` variables, or a [secrets backend](https://airflow.apache.org/docs/apache-airflow/stable/security/secrets/secrets-backend/index.html). Rotation is an Airflow change; dte picks it up on the next run. See [Connections](../connections/index.md).

## Env variables dte reads

Set on every Airflow component (api-server, scheduler, dag-processor, workers).

| Variable | Purpose |
| -------- | ------- |
| `DTE_DATABASE_URL` | Required. A Postgres database for dte's tables (`postgresql://…`, `dte` schema). Recommended: its own database and role with no access to Airflow's; Airflow's metadata database also works. Airflow 3 hides its own URL from DAG parsing and tasks, so dte needs it passed explicitly. |
| `DTE_ARTIFACT_DIR` | Where run artifacts go. Use a path every component shares. |
| `DTE_AIRFLOW_URL` | How the api-server reaches Airflow's REST API to trigger runs. Default `http://localhost:8080`. |
| `DTE_RUN_TIMEOUT_SECONDS` | A run's `execution_timeout` when its schedule sets none. Default `1800` (30 min). |
| `DTE_PREVIEW_TIMEOUT_SECONDS` | Preview, schema inference and dry runs give up with a 504 after this. Default `30`. |
| `DTE_RUN_MAX_ROWS` | Most rows a run writes. Default `10000000`. |
| `DTE_DUCKDB_MEMORY_LIMIT` | Memory cap per DuckDB connection (one per run or preview). Default `2GB`; empty means DuckDB's own default, 80% of RAM. |
| `DTE_DUCKDB_THREADS` | DuckDB threads per connection. Default: every core. |
| `DTE_DUCKDB_TEMP_DIR` | Where DuckDB spills past the memory cap. Default `<tmp>/dte-duckdb`. |
| `DTE_PIPELINE_STORE` | `postgres` (default) or `file`. See [Pipelines in git](../pipelines/in-git.md). |
| `DTE_PIPELINES_DIR` | Pipeline files in `file` mode. Share it between the api-server and dag-processor. |
| `DTE_PIPELINES_GIT_COMMIT` | `true` commits each save when `DTE_PIPELINES_DIR` is a git checkout. Default `false`. |

## `.env` (Docker Compose only)

`scripts/bootstrap.sh` writes a starter `.env` with a fresh Fernet key, JWT secret and admin password. Don't commit it.
