# Troubleshooting

Read the red panel: dte shows the underlying error in full. For a run, Airflow's task log for that dag run has the rest.

## A connection type is greyed out

Its Airflow provider isn't installed. Install the named package on every component ([extras](self-hosting/install-plugin.md#1-install-the-package)) and restart.

## Connection test fails

If **Test** says it's disabled, set `AIRFLOW__CORE__TEST_CONNECTION=Enabled`.

| Message contains | Try this |
| ---------------- | -------- |
| `403` or `Forbidden` (S3/GCS/Azure) | Wrong keys, a missing role permission, or the bucket doesn't allow listing. Check the connection in **Admin ▸ Connections** and your cloud console. |
| `NoSuchBucket` | Wrong region, or the wrong `endpoint_url` (for MinIO/S3-compatible stores) in the connection's extra. |
| `connection refused` (database) | Wrong host/port, or the Airflow workers can't reach the database. |
| `password authentication failed` | Wrong credentials in the Airflow connection. |
| `SSL required` / TLS error | Set the provider's SSL option in the connection's extra (for Postgres, `"sslmode": "require"`). |

## The DAG file fails to import with `DTE_DATABASE_URL`

Set `DTE_DATABASE_URL` on every Airflow component. See [Install](self-hosting/install-plugin.md#2-set-dte_database_url).

## Infer schema returns nothing

- The folder is empty, or the pattern matches nothing (check for a trailing space).
- The file isn't valid, e.g. an empty CSV or malformed JSON.
- The **folder** field holds a file. Move the filename into **files**.

## Preview goes red

| Message contains | What it means | Fix |
| ---------------- | ------------- | --- |
| `column ... not found` | A step references a field that doesn't exist. It's usually a typo, or the source schema changed. | Re-infer the schema, then fix the step. |
| `cannot cast` | A Retype step can't convert a value (e.g. `"abc"` → int). | Filter out the bad rows first, or pick a different target type. |
| `syntax error` (Filter Advanced, Map expression) | Your expression isn't valid SQL. | Try the Basic tab, or fix the expression. |
| `division by zero` | An expression divides by a zero value in the sample. | Guard it with a case: `case when x = 0 then null else y / x end`. |

## A run fails

- Source unreachable: a database down, credentials expired, a file moved. Fix and rerun. Nothing was written.
- Destination refused the write: schema mismatch, permissions, or an unwritable path. Fix the destination or pipeline.

## A run stays `pending`

The dag run is queued and nothing has picked it up.

- Check the scheduler is running and `dte__<pipeline id>` shows in Airflow without an import error.
- Overlap: Skip runs one at a time, so a manual run waits behind a scheduled one.
- Check Airflow's pools and `parallelism`.

## A "Referenced by" error on delete

A pipeline uses that source or destination. The error lists which. Update or delete those first.

## Still stuck?

Check the [FAQ](faq.md), or open an issue or discussion on [GitHub](https://github.com/flowexperts/dte-airflow).
