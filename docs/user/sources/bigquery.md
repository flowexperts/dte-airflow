# BigQuery

Read BigQuery tables as a [SQL database source](index.md). Steps push down into BigQuery, so filters and aggregations run there and only the result comes back.

**Read [Cost](#cost) before you point dte at a large table.** BigQuery charges for every byte a query scans, and `LIMIT` doesn't reduce that.

## 1. Create the connection

In Airflow, **Admin → Connections**, add a connection of type `google_cloud_platform` with this extra:

```json
{
  "dte_type": "bigquery",
  "project": "my-billing-project",
  "dte_max_bytes_billed": 1099511627776
}
```

- `dte_type: bigquery` makes dte use the connection for BigQuery. Without it, a `google_cloud_platform` connection is treated as GCS. A `gcpbigquery` connection works too, with no `dte_type` needed.
- `project` is the **billing project**. Every query runs, and is billed, there, even when it reads another project's tables.
- `dte_max_bytes_billed` is the [spending cap](#the-cap), in bytes. `1099511627776` is 1 TiB. Set one.

Requires `apache-airflow-providers-google`, which also needs the `google-cloud-bigquery` package.

### Credentials

The Google provider does the auth, so any of its methods work. Pick one and add it to the same extra:

| Method | Extra | When |
| ------ | ----- | ---- |
| Service account key | `"keyfile_dict": "<the key JSON>"` or `"key_path": "/path/key.json"` | Production. Give the account `roles/bigquery.jobUser` on the billing project, plus `roles/bigquery.dataViewer` on the datasets it reads (public datasets need no grant) |
| Your own login | `"credential_config_file": "/path/adc.json"` | Local dev. Run `gcloud auth application-default login` and copy `~/.config/gcloud/application_default_credentials.json` to a path **every** Airflow container can read (the api-server runs previews, the scheduler runs pipelines) |
| Workload identity / attached service account | nothing | Airflow running on GCP; the provider picks up the environment's credentials |

Your own login acts with your full permissions. Don't use it in production.

## 2. Create the source

**Sources → New source → SQL database**, pick the connection, and choose the dataset in **Schema**. Pick the table when you add the source to a pipeline.

The Schema list shows the billing project's datasets. To read another project's dataset, such as a public one, use its full name `project.dataset` (e.g. `bigquery-public-data.samples`). The list can't offer those, so create the source through the API:

```bash
curl -X POST "$AIRFLOW/dte/api/sources" -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{
  "id": "bq_samples", "name": "bq_samples", "connection_id": "bq_default",
  "source_type": "sql_database", "table": "bq_samples",
  "config": {"schema": "bigquery-public-data.samples"}
}'
```

## 3. Build and run

Build the pipeline as usual. The first step on a big table should be a filter on its partition column (see [Cost](#cost)). Destinations can be anything; the result is staged out of BigQuery and written by dte.

## Cost

BigQuery's on-demand price is about **$6.25 per TiB scanned**, with the first 1 TiB each month free. It bills for every column a query reads across every row it has to look at, even if it returns 5 rows. A `LIMIT 5` on a 1 PB table can still cost thousands of dollars. Some numbers:

| Query | Scans | Cost |
| ----- | ----- | ---- |
| Any query on `samples.shakespeare` (6 MB) | 10 MB (the per-query minimum) | ~$0 |
| `pypi.file_downloads`, 2 columns, filtered on `project` | 58 GiB | ~$0.35 |
| `pypi.file_downloads`, downloads per project, last 30 days | 2.9 TB | ~$12–18 |
| `pypi.file_downloads`, `SELECT *`, no date filter | ~1.4 PB | ~$9,000 |

dte guards against this four ways.

### Previews use a sample

Building a pipeline, editing steps and inferring the schema never query the live table. The first time a BigQuery table is used, dte copies a 1,000-row sample with BigQuery's free row-listing API and caches it for a day. Every preview after that runs on the sample, locally and for free. The preview says so: *Preview on 1,000-row sample · taken 2h ago · Refresh*.

Because it's a sample, a selective filter can show 0 rows even when the real table has matches. **Preview on live data** runs the pipeline against BigQuery. If the query would cost more than the confirmation threshold (below), it shows the cost first and runs only after you confirm. The next edit goes back to the sample.

Sample size and freshness: `DTE_SAMPLE_ROWS` (default `1000`) and `DTE_SAMPLE_TTL_SECONDS` (default `86400`).

### Big runs ask first

**Run** on a pipeline with a BigQuery source does a free dry run of the compiled query. Filters count, so a date filter shows up in the number.

- **Under about $1** (160 GiB at list price), the run just starts. Asking on every run teaches people to click through the question.
- **Over that**, the Run dialog says what it will cost: *This run will cost about $18.75 on BigQuery.* One click on **Run** starts it.
- **Over the connection's cap**, the dialog says the run would read more than the connection allows and to add a filter or ask an admin to raise the limit. **Run** stays off, since BigQuery would refuse it.

Change the threshold per connection with `dte_confirm_above_bytes` in its extras (`0` asks on every run).

The estimate is a dry run of the query dte will send. If the pipeline has a step that runs inside dte rather than BigQuery (extract, structure, pivot), or joins BigQuery with another source, dte prices each BigQuery table in full instead, so the estimate errs high.

### The cap

`dte_max_bytes_billed` on the connection is passed to BigQuery as `maximum_bytes_billed` on every query: previews, runs and table browsing. BigQuery refuses an over-cap query **before running it**, so nothing is billed, and the run fails with *Query needs at least X billed, above this connection's cap of Y*.

The cap is the only guard on **scheduled runs**, since no one is there to confirm an estimate. Set it to the most you'd accept for one query. With no cap, nothing stops an expensive scheduled run.

### Partition filters

Big tables are usually partitioned by date, and BigQuery skips partitions a query filters out. If a pipeline reads a partitioned table and no filter step mentions its partition column, the builder warns: *No filter on `timestamp` — this run scans the whole table.* Make that filter the first step:

```sql
timestamp >= current_timestamp - INTERVAL 7 DAY
```

Write step SQL in DuckDB's dialect, as everywhere in dte; it's translated to BigQuery's (`CURRENT_TIMESTAMP() - INTERVAL '7' DAY`). BigQuery-only syntax such as `TIMESTAMP_SUB` fails on the sample preview.

Selecting only the columns you need also cuts the bill: BigQuery charges per column read.

### Through the API

The API enforces the same rule, so a script can't skip it. Below the threshold these calls just run; above it:

- `GET /dte/api/pipelines/{id}/preview?live=true` returns only `{"estimate": …}` and runs nothing. Add `&confirm=true` to run it.
- `POST /dte/api/pipelines/{id}/trigger` returns `{"estimate": …, "enqueued": false}`. Send `{"confirm": true}` to start the run.
- `POST /dte/api/pipelines/estimate` prices an unsaved pipeline.

For a hard monthly ceiling beyond dte, set [custom quotas](https://cloud.google.com/bigquery/quotas#custom_quotas) (bytes per day) and a budget alert on the billing project.

## Snowflake

Snowflake sources get the same sampling, estimate and confirmation. Snowflake bills warehouse time rather than bytes, so dte shows no price and the cap is a statement timeout. See [Snowflake](../connections/snowflake.md#cost).
