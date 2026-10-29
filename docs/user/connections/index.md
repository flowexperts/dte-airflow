# Connections

A connection is dte's login to one system — a database, a cloud bucket, an API. It holds credentials only. It doesn't know which table or which folder.

dte doesn't keep its own connections. It uses **Airflow connections**, and the Airflow provider that owns each connection type does the auth. Create them where you already do: **Admin → Connections** in Airflow, `AIRFLOW_CONN_*` environment variables, or a secrets backend.

## Why the split

Sources and destinations point at a connection by name. This means:

- **Rotate credentials once.** Update the connection, every pipeline that uses it picks up the new value on the next run.
- **Share safely.** Two pipelines reading different tables in the same database share one connection.
- **Same auth as your other DAGs.** An `aws` connection on an IAM role, an Azure service principal or managed identity, a GCP service account — if it works in an Airflow task, it works in dte.

## Every connection type

dte offers a type only when its provider is installed in your Airflow. A type whose provider is missing shows in the source picker as disabled, with the package to install.

| Airflow connection type | Provider package | Use it for |
| ----------------------- | ---------------- | ---------- |
| `fs` | `apache-airflow-providers-standard` | Files on the machines Airflow runs on |
| `aws` | `apache-airflow-providers-amazon[s3fs]` | Reading and writing S3 (and S3-compatible stores: set `endpoint_url` in the extra) |
| `google_cloud_platform` | `apache-airflow-providers-google` | Reading and writing GCS. Set extra `dte_type: bigquery` to use it for BigQuery instead |
| `gcpbigquery` | `apache-airflow-providers-google` | Reading and writing BigQuery |
| `wasb`, `adls`, `azure_data_lake` | `apache-airflow-providers-microsoft-azure` | Reading and writing Azure Blob / ADLS |
| `sftp` | `apache-airflow-providers-sftp` + `sshfs` | Reading and writing files over SFTP |
| `postgres` | `apache-airflow-providers-postgres` | Reading and writing tables |
| `mysql` | `apache-airflow-providers-mysql` | Reading and writing tables |
| `mssql` | `apache-airflow-providers-microsoft-mssql` | Reading and writing tables (needs Microsoft ODBC Driver 18) |
| `snowflake` | `apache-airflow-providers-snowflake` | Reading and writing tables |
| `sqlite` | `apache-airflow-providers-sqlite` | Reading local `.db` files |
| `mongo` | `apache-airflow-providers-mongo` | Reading collections |
| `http` | `apache-airflow-providers-http` | Pulling data from a JSON API (login/password become basic or bearer auth) |

Fill in each connection the way the provider documents it. dte reads SQL connections through the provider hook's SQLAlchemy URL and opens files through the provider's filesystem, so whatever the provider accepts, dte accepts.

## Which connections dte lists

The connection picker lists connections in Airflow's metadata database and `AIRFLOW_CONN_*` variables. A secrets backend can't be enumerated, so its connections resolve at run time but don't appear in the picker; set `connection_id` on the source or destination through the API.

## Test before you use

**Test** calls the provider's own connection test. Airflow turns connection testing off by default; enable it with `[core] test_connection = Enabled` (`AIRFLOW__CORE__TEST_CONNECTION=Enabled`). Until then **Test** says it's disabled.

A failure shows the provider's message. Fix the connection in Airflow and test again. A failure caught here is one you won't chase inside a pipeline run.

## Which connection goes with which source / destination

Not every combination is valid. dte will stop you at save if you pick a mismatched pair.

- **`fs`** → filesystem sources; JSON, CSV, Excel, Parquet file destinations
- **`aws`, `google_cloud_platform`, `wasb`/`adls`, `sftp`** → the matching file source (S3, GCS, Azure, SFTP); JSON, CSV, Excel, Parquet file destinations at a matching URL
- **`postgres`** → SQL database sources; PostgreSQL destinations
- **`mysql`, `mssql`, `snowflake`, `gcpbigquery` (or `google_cloud_platform` with `dte_type: bigquery`)** → SQL database sources; SQL database destinations
- **`sqlite`** → SQL database sources (read only)
- **`mongo`** → MongoDB sources
- **`http`** → REST API sources
