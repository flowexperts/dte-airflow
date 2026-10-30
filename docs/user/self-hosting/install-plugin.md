# Install into your own Airflow

DTE is an Airflow 3.3+ plugin. To add it to an Airflow you already run, you
need four things: the package, its migrations, one DAG file and one
environment variable. To try DTE without an Airflow of your own, use the
[Docker Compose stack](install.md) instead.

## Requirements

- Airflow 3.3 or later on Python 3.12.
- A **Postgres** database for DTE's tables (a `dte` schema). Its own database
  is the recommended setup; Airflow's metadata database also works.
- The package installed on every Airflow component: api-server, scheduler,
  dag-processor and workers.

## 1. Install the package

Install with your Airflow's own constraints file, unmodified: set `AIRFLOW`
and `PY` to the versions you run. DTE follows the versions Airflow pins; it
never asks you to change them, and it doesn't upgrade or downgrade Airflow
itself.

```bash
AIRFLOW=3.3.2 PY=3.12
curl -fsSLo constraints.txt \
  https://raw.githubusercontent.com/apache/airflow/constraints-$AIRFLOW/constraints-$PY.txt
pip install dte-airflow --constraint constraints.txt
```

Extras name the Airflow provider (and the filesystem package it needs) for a
connection type. Add the ones your Airflow doesn't already have:

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

The stock `apache/airflow` image already has the google, microsoft-azure, sftp,
postgres, mysql, snowflake and http providers, with every driver DTE needs to
read and write those databases. It lacks `s3fs` and `sshfs`, so add `amazon`
for S3 and `sftp` for SFTP, and it has no mongo or mssql provider.
On a slimmer Airflow build without those drivers, the `postgres-writer`,
`mysql-writer`, `snowflake-writer` and `bigquery-writer` extras add them.

In a Dockerfile built `FROM apache/airflow:3.3.2-python3.12`, run the same
lines as `RUN` steps.

## 2. Set `DTE_DATABASE_URL`

Set it on every component, pointing at a Postgres database for DTE. Give DTE
its own database and role, with no access to Airflow's:

```sql
CREATE ROLE dte LOGIN PASSWORD '...';
CREATE DATABASE dte OWNER dte;
```

```bash
DTE_DATABASE_URL=postgresql://dte:...@host:5432/dte
```

DTE reads its pipelines in DAG parsing and tasks, where Airflow 3 hides its own
database URL, so the URL has to be passed explicitly. Without it, the DAG file
fails to import with an error that names `DTE_DATABASE_URL`. Run history still
comes from Airflow: the api-server reads dag runs through Airflow's own session
and merges them with DTE's results, so DTE's role never needs Airflow's tables.
Pointing `DTE_DATABASE_URL` at Airflow's metadata database works too.

Optional:

| Variable | Default | |
|---|---|---|
| `DTE_ARTIFACT_DIR` | `.dte-artifacts` (relative to the process) | Run artifacts. Use a path every component shares. |
| `DTE_AIRFLOW_URL` | `http://localhost:8080` | How the api-server reaches Airflow's REST API to trigger runs. |

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

Every DTE pipeline becomes a `dte__<pipeline id>` DAG. DTE's DAGs are created
unpaused, so runs start without a click, whatever your
`dags_are_paused_at_creation` setting is.

## 5. Restart Airflow

Restart the api-server, scheduler and dag-processor. DTE appears under
**Plugins ▸ DTE Pipelines**, with sources, destinations and lookup tables
under **Admin**.

## Connections

Whatever Airflow provider is installed, DTE supports that connection. The
provider does the auth: an `aws` connection that uses an IAM role or
assume-role, an Azure service principal or managed identity, or a GCP
service account works in DTE exactly as it does in your other DAGs.

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

DTE only offers a type when its provider (and, for files, the provider's
filesystem package) is installed. Anything else shows in the source picker
as disabled, naming the package to install.

Connections resolve the way they do for any task: secrets backends,
`AIRFLOW_CONN_*` environment variables, then the metadata database. The
connection picker lists the metadata database and `AIRFLOW_CONN_*` variables.
A secrets backend can't be enumerated, so its connections resolve at run time
but don't appear in the picker yet; set their `connection_id` through the API.

**Test** on a connection calls the provider's own connection test. It
follows Airflow's `[core] test_connection` setting, which is off by default.
