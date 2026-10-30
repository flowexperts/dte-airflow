# Secrets & environment

dte stores no credentials. Connections are Airflow connections, kept in the metadata database (Fernet-encrypted), `AIRFLOW_CONN_*` variables, or a [secrets backend](https://airflow.apache.org/docs/apache-airflow/stable/security/secrets/secrets-backend/index.html). Rotation is an Airflow change; dte picks it up on the next run. See [Connections](../connections/index.md).

## Env variables dte reads

Set on every Airflow component (api-server, scheduler, dag-processor, workers).

| Variable | Purpose |
| -------- | ------- |
| `DTE_DATABASE_URL` | Required. A Postgres database for dte's tables (`postgresql://…`, `dte` schema). Recommended: its own database and role with no access to Airflow's; Airflow's metadata database also works. Airflow 3 hides its own URL from DAG parsing and tasks, so dte needs it passed explicitly. |
| `DTE_ARTIFACT_DIR` | Where run artifacts go. Use a path every component shares. |
| `DTE_AIRFLOW_URL` | How the api-server reaches Airflow's REST API to trigger runs. Default `http://localhost:8080`. |

## `.env` (Docker Compose only)

`scripts/bootstrap.sh` writes a starter `.env` with a fresh Fernet key, JWT secret and admin password. Don't commit it.
