# Architecture overview

A quick tour of what runs where. For the exhaustive version, see [`ARCHITECTURE.md`](https://github.com/flowexperts/dte-airflow/blob/main/ARCHITECTURE.md) in the repo.

## It's an Airflow plugin

dte has no server of its own. One Python package, `dte-airflow`, installed on every Airflow component, adds:

- **An API**, mounted on Airflow's api-server at `/dte/api`. It holds the business logic: pipelines, sources, destinations, preview and schema inference.
- **A UI**, registered as an Airflow `react_apps` plugin. It renders natively inside Airflow at `/plugin/dte`, follows Airflow's theme, and adds itself to Airflow's left rail.
- **A DAG factory**, the one-line `dte_dags.py` in your DAGs folder. It turns every pipeline into a `dte__<pipeline id>` DAG.
- **An operator**, `DtePipelineOperator`, which executes a pipeline as an Airflow task.

Airflow owns login, permissions, connections, scheduling and run history. dte uses all of them rather than keeping its own.

## The execution stack

A pipeline runs inside an Airflow task. The stack, top to bottom:

- **ibis** is the compiler DSL. Each step maps to an ibis operation, and the compiler stitches them into one query.
- **DuckDB** is the query engine. Transforms compile to DuckDB SQL and execute in-process. A pipeline whose sources are all in one database can push the query down to that database instead.
- **dlt** handles `mongodb` and `rest_api` sources (pagination, auth, normalisation), plus some database writes.

DuckDB reads local files directly. S3, GCS, Azure and SFTP files are read and written through the Airflow provider's fsspec filesystem (`ObjectStoragePath`), so the provider does the auth. SQL sources open the database with ibis, using the URL from the provider hook.

## Where credentials live

In Airflow. Connections are Airflow connections (in the metadata DB, `AIRFLOW_CONN_*` variables or a secrets backend), and dte resolves them at run time through `BaseHook.get_connection` and the provider. Sources and destinations reference a connection by id and hold only the "where inside" details (bucket, table, path). See [Secrets & environment](../self-hosting/secrets.md).

## Storage layout

- **Postgres**: Airflow's metadata database. dte's tables (`pipelines`, `sources`, `destinations`, `lookup_tables`, `run_results`…) live in its `dte` schema. Connections, users and dag runs are Airflow's own tables.
- **`DTE_ARTIFACT_DIR`**: cached document extractions and model calls. Share it across components.
- **In-process**: an ephemeral DuckDB connection per run. Nothing persists there.

## How a run happens

1. A user clicks **▶ Run**, or the DAG's schedule fires.
2. For a manual run, dte's API asks Airflow's REST API to trigger the `dte__<pipeline id>` DAG, forwarding the user's own credentials so Airflow's permissions apply.
3. The scheduler queues the dag run, and an executor runs `DtePipelineOperator`, which:
   - Loads the revision the run was started against, and its sources and destination
   - Resolves their connections through Airflow
   - Loads each source into the run's DuckDB connection
   - Compiles the steps into one ibis expression, executes it, and writes to the destination
4. The outcome (status, rows written, quality results, the SQL that ran) goes into `dte.run_results`, keyed by the dag run id. Airflow keeps the task state and the log.
5. The UI polls the run every 2 seconds until it's finished.

## Where to dig deeper

- Data flow specifics: [Data flow](data-flow.md)
- Full internals: [`ARCHITECTURE.md`](https://github.com/flowexperts/dte-airflow/blob/main/ARCHITECTURE.md)
- Feature history and rationale: [`plans/`](https://github.com/flowexperts/dte-airflow/tree/main/plans). Every non-trivial change gets a numbered plan.
