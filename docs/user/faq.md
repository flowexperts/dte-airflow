# FAQ

## Do I need my own Airflow?

To run dte for real, yes: it's a plugin for Airflow 3.3+ ([install](self-hosting/install-plugin.md)). To try it, the [Docker Compose stack](self-hosting/install.md) brings its own Airflow.

## Can I schedule a pipeline?

Yes. Give it a [schedule](pipelines/scheduling.md) and it becomes the cron of the pipeline's Airflow DAG.

## Can I run pipeline B after pipeline A?

Use plain Airflow: write a DAG that triggers or waits on the `dte__<pipeline id>` DAGs.

## Can I rename a pipeline id?

No. The id names the Airflow DAG and appears in run history, so it's fixed after creation. The **Name** is free to change any time.

## Can two pipelines write to the same table?

Yes, but be careful with the write mode on a database destination. Two pipelines both set to **Replace** overwrite each other's results on every run. **Append** or **Merge** are usually what you want.

## Can I edit a source without breaking the pipelines that use it?

You can edit it, but the change affects every pipeline that reads that source on its next run. The source form warns you.

If you need to change a source drastically, duplicate it, edit the copy, then switch pipelines over one by one.

## What happens to a running pipeline if I edit it mid-run?

Nothing. Each run uses the exact revision it started against, and your edit becomes a new revision that applies to the next run.

## Where does the output actually go?

Wherever the destination points. For a local file destination (an `fs` connection), that's a path on the machine that runs the Airflow task, so use storage every Airflow worker shares, or object storage.

## Can I preview more than 20 rows?

Not from the UI. Preview is for shape, not scale. Run the pipeline and peek at the output.

## The field picker is empty. Why?

The source's schema hasn't been inferred yet. Click **Infer schema** on the source card.

## How do I filter on a nested field?

Use dot syntax, `order.amount > 100`. See [Field names](pipelines/field-refs.md).

## Can I use a Google Sheet as a source?

Not directly. Export or sync the sheet to a database or a CSV file, then read that.

## Who can see my pipelines?

Airflow decides. dte follows Airflow's auth manager and DAG permissions.

## Is my data leaving my infrastructure?

No. dte runs inside your Airflow, reads from your sources and writes to your destinations. The exception is **Structure fields** with Claude or OpenAI, which sends document text to that provider through your own Airflow connection. The regex provider stays offline.
