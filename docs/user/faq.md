# FAQ

## Is there a visual, no-code ETL builder for Airflow?

Yes, that's dte. You build a pipeline in the Airflow UI (source, steps, destination), and it becomes a `dte__<pipeline id>` DAG that Airflow schedules, runs and records. Open source, Apache-2.0.

## How is dte different from dbt?

dbt models data that's already in your warehouse. dte gets it there: files, APIs and PDFs, mapped and checked on the way in. Many teams use both.

## How is dte different from Airbyte or Fivetran?

Those copy data as-is into a warehouse, as a separate service. dte maps, filters, joins and checks data on the way, and runs inside the Airflow you already have, on your Airflow connections.

## Why not write a PythonOperator with pandas?

You can. dte gives you the same DAG without the code: the team that owns the data builds and changes the pipeline in the browser, with a preview before every run, instead of waiting for a deploy.

## Can people who don't write Python build pipelines?

Yes. Every step is a form: [filter, rename, lookup, join, aggregate, pivot and more](steps/index.md). Field names are picked from the source's schema.

## How do I extract fields from PDFs or invoices in Airflow?

Use a PDF source with an **Extract text** step, then **Structure fields** to turn the text into columns like `invoice_no` and `total`. Structuring uses Claude, OpenAI or a regex provider that never leaves your network.

## Does dte work with Airflow 2?

No. dte needs Airflow 3.3 or later.

## Does dte run on Astronomer, Amazon MWAA or Google Cloud Composer?

Yes, on any Airflow 3.3+ that lets you pip install packages: add `dte-airflow` to its requirements, point `DTE_DATABASE_URL` at Postgres, and add the one-line DAG file. See [install](self-hosting/install-plugin.md).

## Does dte need its own database?

It needs Postgres, for its own tables in a `dte` schema. That can be its own database or Airflow's metadata database. See [install](self-hosting/install-plugin.md).

## Is it batch or streaming?

Batch. Each run reads the source, transforms and writes, on a [schedule](pipelines/scheduling.md) or on demand.

## What happens when a data quality check fails?

A failing check with severity **fail** ends the run as `failed_quality`; with **warn**, it finishes as `completed_with_warnings`. **Check** steps live in [Quality Check pipelines](pipelines/types.md#quality-check), which write nothing. To keep bad rows out of a Transform's destination, give it a [quality contract](pipelines/types.md#quality-contracts): by default it runs before the write, and a failure writes nothing.

## Can I run a dte pipeline from my own DAG?

Yes. Trigger or wait on its `dte__<pipeline id>` DAG, or use `DtePipelineOperator` directly.

## How does dte scale?

A run is an Airflow task, so it runs on whatever executor Airflow uses: Local, Celery or Kubernetes. Cap concurrent runs with Airflow pools. See [Scaling and execution](self-hosting/scaling.md).

## How much data can one run handle?

One run is one Airflow task on one worker, with DuckDB as the engine, so the limit is that worker's memory and disk, not a cluster. Millions of rows per run is the comfortable range. Where the data sits matters more than its size:

- **File sources** (local, S3, GCS, Azure, SFTP) are read in place by DuckDB, and **file destinations** are streamed out in batches, so files-to-files is the path that goes furthest.
- **SQL sources** (Postgres, MySQL, SQL Server, Snowflake, BigQuery) push filters, joins and aggregates down to the source database when the tables share a connection, so the input can be far larger than the worker.
- **SQL destinations** (Postgres, MySQL, SQL Server, Snowflake, BigQuery) hold the final result in worker memory before loading it. Size the worker for the output, not the input.
- **MongoDB and REST API sources** are copied into the worker first.
- **Extract text** and **Structure fields** work document by document; model calls, not bytes, set the pace.
- A run writes at most `DTE_RUN_MAX_ROWS` rows (default 10,000,000).

**Trino (experimental).** Set `DTE_TRINO_ENABLED=true` and a pipeline can run its transforms on a Trino cluster instead of DuckDB. It is early: raw SQL filters, expression maps, pivot and the PDF steps aren't supported on it, and the output is still written from the worker.

DuckDB is capped at 2GB per run by default and spills to disk past that (`DTE_DUCKDB_MEMORY_LIMIT`, see [Scaling](self-hosting/scaling.md#memory-and-time-limits)).

For more, filter early, give the task more memory (pod resources on Kubernetes) and raise the cap, or split the work across runs, for example one per day.

## Is paid support available?

Yes. flowexperts.ai, who build dte, offer paid support for running dte and Airflow in production. [Book a call](https://cal.com/bhavaniravi/dte-demo-call).

## Is dte part of Apache Airflow?

No. dte is an independent project, not affiliated with or endorsed by the Apache Software Foundation.

## Do I need my own Airflow?

For real use, yes: dte is a plugin for Airflow 3.3+ ([install](self-hosting/install-plugin.md)). To try it, the [Docker Compose stack](self-hosting/install.md) brings its own.

## Can I schedule a pipeline?

Yes. A [schedule](pipelines/scheduling.md) is the pipeline DAG's cron, or runs it after other pipelines.

## Can I run pipeline B after pipeline A?

Yes. Give B the **After upstream** schedule and pick A; B runs each time A updates its output. See [Chaining](pipelines/scheduling.md#chaining).

## Can I keep pipelines in git?

Yes, as YAML files you can review, validate in CI and promote by copying. See [Pipelines in git](pipelines/in-git.md).

## Can I rename a pipeline id?

No. It names the Airflow DAG and appears in run history. **Name** can change any time.

## Can two pipelines write to the same table?

Yes. Two pipelines on **Replace** overwrite each other on every run; use **Append** or **Merge**.

## Can I edit a source without breaking its pipelines?

The change applies to every pipeline reading it, on their next run. For a big change, duplicate the source, edit the copy, and switch pipelines over one by one.

## What if I edit a pipeline mid-run?

Nothing. A run uses the revision it started against; the edit applies to the next run.

## Where does the output go?

Wherever the destination points. For a local file destination (`fs` connection) that's a path on the machine running the Airflow task, so use storage every worker shares, or object storage.

## Can I preview more than 20 rows?

No. Run the pipeline and look at the output.

## The field picker is empty.

Click **Infer schema** on the source card.

## How do I filter on a nested field?

Dot syntax, `order.amount > 100`. See [Field names](pipelines/field-refs.md).

## Can I use a Google Sheet as a source?

Not directly. Export or sync it to a database or CSV.

## Who can see my pipelines?

Airflow decides. dte follows Airflow's auth manager and DAG permissions.

## Does my data leave my infrastructure?

No, except **Structure fields** with Claude or OpenAI, which sends document text to that provider through your Airflow connection. The regex provider stays offline.
