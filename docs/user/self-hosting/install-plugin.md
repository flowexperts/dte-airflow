# Install into your own Airflow

dte is an Airflow 3.3+ plugin. You need the package, its migrations, one DAG file and one environment variable. To try it without your own Airflow, use the [Docker Compose stack](install.md).

## Requirements

- Airflow 3.3+ on Python 3.12.
- A **Postgres** database for dte's tables (a `dte` schema). Its own database is recommended; Airflow's metadata database also works.
- The package on every component: api-server, scheduler, dag-processor and workers.

## 1. Install the package

Use your Airflow's own constraints file, unmodified. dte follows the versions Airflow pins and never asks you to change them. Set `AIRFLOW` and `PY` to the versions you run.

```bash
AIRFLOW=3.3.2 PY=3.12
curl -fsSLo constraints.txt \
  https://raw.githubusercontent.com/apache/airflow/constraints-$AIRFLOW/constraints-$PY.txt
pip install dte-airflow --constraint constraints.txt
```

Extras add the provider (and filesystem package) for a connection type:

| Extra | Adds |
|---|---|
| `amazon` | S3 (`apache-airflow-providers-amazon[s3fs]`) |
| `google` | GCS and BigQuery (`apache-airflow-providers-google`) |
| `azure` | Azure Blob / ADLS (`apache-airflow-providers-microsoft-azure`) |
| `sftp` | SFTP (`apache-airflow-providers-sftp` + `sshfs`) |
| `mongo` | MongoDB (`apache-airflow-providers-mongo`) |
| `mssql` | SQL Server (provider + ODBC; needs Microsoft ODBC Driver 18 on the host) |
| `unstructured` | PDF extraction |
| `models` | Claude/OpenAI `structure` steps (`apache-airflow-providers-anthropic`, `-openai`); the API key is an `anthropic` / `openai` Airflow connection |

For example: `pip install "dte-airflow[amazon,unstructured]" --constraint constraints.txt`.

The stock `apache/airflow` image has the google, microsoft-azure, sftp, postgres, mysql, snowflake and http providers, with every driver dte needs. It lacks `s3fs` and `sshfs` (add `amazon` for S3, `sftp` for SFTP) and has no mongo or mssql provider. On a slimmer build, the `postgres-writer`, `mysql-writer`, `snowflake-writer` and `bigquery-writer` extras add the drivers.

In a Dockerfile `FROM apache/airflow:3.3.2-python3.12`, run the same lines as `RUN` steps.

## 2. Set `DTE_DATABASE_URL`

Set it on every component. Give dte its own database and role, with no access to Airflow's:

```sql
CREATE ROLE dte LOGIN PASSWORD '...';
CREATE DATABASE dte OWNER dte;
```

```bash
DTE_DATABASE_URL=postgresql://dte:...@host:5432/dte
```

Airflow 3 hides its own database URL from DAG parsing and tasks, so dte needs this passed explicitly. Without it the DAG file fails to import with an error naming `DTE_DATABASE_URL`. Run history still comes from Airflow: the api-server reads dag runs through Airflow's session and merges them with dte's results, so dte's role never needs Airflow's tables. Pointing it at Airflow's metadata database also works.

Optional:

| Variable | Default | |
|---|---|---|
| `DTE_ARTIFACT_DIR` | `.dte-artifacts` (relative to the process) | Run artifacts. Use a path every component shares. |
| `DTE_AIRFLOW_URL` | `http://localhost:8080` | How the api-server reaches Airflow's REST API to trigger runs. |

Memory, timeout and pipeline-store settings: [Secrets & environment](secrets.md#env-variables-dte-reads).

## 3. Migrate

Once per install and after every upgrade, with `DTE_DATABASE_URL` set:

```bash
dte db upgrade
```

## 4. Add the DAG file

Put this in your DAGs folder as `dte_dags.py`:

```python
from dte.airflow.dag_factory import build_dags

globals().update(build_dags())
```

Every pipeline becomes a `dte__<pipeline id>` DAG. They're created unpaused, whatever `dags_are_paused_at_creation` says.

## 5. Restart Airflow

Restart the api-server, scheduler and dag-processor. dte appears under **Plugins ▸ DTE Pipelines**, with sources, destinations and lookup tables under **Admin**.

## Connections

dte supports any connection whose Airflow provider is installed, and the provider does the auth (IAM roles, Azure service principals, GCP service accounts).

| Airflow connection type | In DTE | Through |
|---|---|---|
| `aws` | S3 source / file destination | the amazon provider's filesystem (`s3://`) |
| `google_cloud_platform` | GCS (`gs://`, `gcs://`); BigQuery with extra `dte_type: bigquery` | the google provider (its filesystem; for BigQuery, its credentials) |
| `gcpbigquery` | BigQuery | the google provider's credentials |
| `wasb`, `adls`, `azure_data_lake` | Azure Blob / ADLS (`abfs://`, `az://`) | the microsoft-azure provider |
| `sftp` | SFTP (`sftp://`) | the sftp provider + `sshfs` |
| `postgres`, `mysql`, `mssql`, `sqlite`, `snowflake` | SQL source / destination | the provider hook's SQLAlchemy URL |
| `mongo` | MongoDB source | the mongo provider |
| `http` | REST API source | login/password as basic or bearer auth |
| `fs` | Local files | |

Types without an installed provider show as disabled in the source picker, naming the package. Connections resolve like any task: secrets backends, `AIRFLOW_CONN_*`, then the metadata database. The picker lists only the last two; for a secrets-backend connection, set `connection_id` through the API. **Test** follows Airflow's `[core] test_connection`, off by default. See [Connections](../connections/index.md).
