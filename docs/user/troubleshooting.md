# Troubleshooting

The pattern: **read the red panel**. dte shows the underlying error in full — not a friendly wrapper. That means the message is often the answer.

Common ones and what to do.

## Connection test fails

| Message contains | Try this |
| ---------------- | -------- |
| `403` or `Forbidden` (S3/GCS/Azure) | Wrong keys, wrong region, or the bucket doesn't allow list. Double-check with your cloud console. |
| `NoSuchBucket` | Wrong region, or wrong endpoint URL (for MinIO/S3-compatible). |
| `connection refused` (database) | Wrong host/port, or the machine dte runs on can't reach the database. Ask your admin. |
| `password authentication failed` | Wrong credentials in the URL. |
| `SSL required` / TLS error | Add `?sslmode=require` (Postgres) to your URL. |

## Infer schema returns nothing

- The folder is empty, or the file pattern matches nothing. Fix the folder or the pattern.
- The file exists but isn't valid — e.g. an empty CSV, malformed JSON. Open it and check.
- For file sources: the **folder** field must be a folder, not a single file. Move the filename into the **files** field.

## Preview goes red

The message says what's wrong. Frequent ones:

| Message contains | What it means | Fix |
| ---------------- | ------------- | --- |
| `column ... not found` | A step references a field that doesn't exist. Usually a typo, or the source schema changed. | Re-infer schema; fix the step. |
| `cannot cast` | A Retype step can't convert a value (e.g. `"abc"` → int). | Filter bad rows first, or pick a different target type. |
| `syntax error` (Filter Advanced, Map expression) | Your expression isn't valid SQL. | Try Basic Filter, or fix the expression. |
| `division by zero` | An expression divides by a zero value in the sample. | Guard with a case: `case when x = 0 then null else y / x end`. |

## Run fails

The run page shows the error in full. Two frequent categories:

- **Source unreachable at run time** — a database went down, credentials expired, a file moved. Fix the source; re-trigger. Nothing else was written.
- **Destination refused the write** — the target table's schema doesn't match, permissions are wrong, the path isn't writeable. Read the message; fix the destination or the pipeline.

## Run stays pending forever

- The app may be busy. Wait a minute and refresh.
- If it's still stuck after a few minutes, check with your admin — see the operator's [runbook](../runbooks/oncall/pipeline-stuck-running.md).

## "Referenced by" error on delete

You tried to delete a connection, source, or destination that a pipeline uses. The error message lists exactly which pipelines. Update or delete those first, then try again.

## Still stuck?

- Preview is your friend — it isolates the problem to a specific step.
- Check the [FAQ](faq.md).
- Ask in the project's issue tracker.
