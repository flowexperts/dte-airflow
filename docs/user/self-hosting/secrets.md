# Secrets & environment

dte stores no credentials of its own. Connections are Airflow connections, so
Airflow keeps them: encrypted in the metadata database with Airflow's Fernet key,
in `AIRFLOW_CONN_*` environment variables, or in whatever
[secrets backend](https://airflow.apache.org/docs/apache-airflow/stable/security/secrets/secrets-backend/index.html)
you configure (Vault, AWS Secrets Manager, GCP Secret Manager, Azure Key Vault).
Rotating a credential is an Airflow change; dte picks it up on the next run.
See [Connections](../connections/index.md).

## Env variables dte reads

Set them on every Airflow component (api-server, scheduler, dag-processor,
workers).

| Variable | Purpose |
| -------- | ------- |
| `DTE_DATABASE_URL` | Required. A Postgres database for dte's tables (`postgresql://…`, `dte` schema). Recommended: its own database and role with no access to Airflow's; Airflow's metadata database also works. Airflow 3 hides its own URL from DAG parsing and tasks, so dte needs it passed explicitly. |
| `DTE_ARTIFACT_DIR` | Where run artifacts go. Use a path every component shares. |
| `DTE_AIRFLOW_URL` | How the api-server reaches Airflow's REST API to trigger runs. Default `http://localhost:8080`. |

## What's in `.env` (Docker Compose stack only)

`scripts/bootstrap.sh` writes a starter `.env` with a fresh Airflow Fernet key,
JWT secret and admin password. Don't commit it.
