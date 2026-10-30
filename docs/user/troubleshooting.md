# Troubleshooting

The pattern: **read the red panel**. dte shows the underlying error in full rather than a friendly wrapper, so the message is often the answer. For a run, Airflow's task log for that dag run has everything.

Here are the common ones and what to do about them.

## A connection type is greyed out

Its Airflow provider isn't installed. The picker names the package; install it on every Airflow component ([extras](self-hosting/install-plugin.md#1-install-the-package)) and restart.

## Connection test fails

If **Test** says it's disabled, that's Airflow's default. Enable it with `AIRFLOW__CORE__TEST_CONNECTION=Enabled`.

| Message contains | Try this |
| ---------------- | -------- |
| `403` or `Forbidden` (S3/GCS/Azure) | Wrong keys, a missing role permission, or the bucket doesn't allow listing. Check the connection in **Admin ▸ Connections** and your cloud console. |
| `NoSuchBucket` | Wrong region, or the wrong `endpoint_url` (for MinIO/S3-compatible stores) in the connection's extra. |
| `connection refused` (database) | Wrong host/port, or the Airflow workers can't reach the database. |
| `password authentication failed` | Wrong credentials in the Airflow connection. |
| `SSL required` / TLS error | Set the provider's SSL option in the connection's extra (for Postgres, `"sslmode": "require"`). |

## The DAG file fails to import with `DATABASE_URL`

Set `DATABASE_URL` on every Airflow component, pointing at the metadata database. See [Install](self-hosting/install-plugin.md#2-set-database_url).

## Infer schema returns nothing

- The folder is empty, or the file pattern matches nothing. Fix the folder or the pattern, and check for a trailing space.
- The file exists but isn't valid, for example an empty CSV or malformed JSON. Open it and check.
- For file sources, the **folder** field must be a folder, not a single file. Move the filename into the **files** field.

## Preview goes red

The message says what's wrong. Frequent ones:

| Message contains | What it means | Fix |
| ---------------- | ------------- | --- |
| `column ... not found` | A step references a field that doesn't exist. It's usually a typo, or the source schema changed. | Re-infer the schema, then fix the step. |
| `cannot cast` | A Retype step can't convert a value (e.g. `"abc"` → int). | Filter out the bad rows first, or pick a different target type. |
| `syntax error` (Filter Advanced, Map expression) | Your expression isn't valid SQL. | Try the Basic tab, or fix the expression. |
| `division by zero` | An expression divides by a zero value in the sample. | Guard it with a case: `case when x = 0 then null else y / x end`. |

## A run fails

The run shows the error in full, and the Airflow task log has the rest. Two frequent categories:

- **Source unreachable at run time.** A database went down, credentials expired, or a file moved. Fix it and run again. Nothing was written.
- **Destination refused the write.** The target table's schema doesn't match, the permissions are wrong, or the path isn't writable. Read the message, then fix the destination or the pipeline.

## A run stays `pending`

The dag run is queued in Airflow and nothing has picked it up yet.

- Check that Airflow's scheduler is running, and that the `dte__<pipeline id>` DAG shows up in Airflow without an import error.
- A schedule with **Overlap: Skip** runs one at a time, so a manual run waits behind a running scheduled one.
- Check Airflow's pools and `parallelism`, which may be full.

## A "Referenced by" error on delete

You tried to delete a source or destination that a pipeline uses. The error lists exactly which pipelines. Update or delete those first, then try again.

## Still stuck?

- Preview is your friend: it isolates the problem to one step.
- Check the [FAQ](faq.md).
- Open an issue or a discussion on [GitHub](https://github.com/flowexperts/dte-airflow).
