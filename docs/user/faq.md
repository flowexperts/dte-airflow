# FAQ

## Do I need my own Airflow?

For real use, yes: dte is a plugin for Airflow 3.3+ ([install](self-hosting/install-plugin.md)). To try it, the [Docker Compose stack](self-hosting/install.md) brings its own.

## Can I schedule a pipeline?

Yes. A [schedule](pipelines/scheduling.md) is the cron of the pipeline's DAG.

## Can I run pipeline B after pipeline A?

Write an Airflow DAG that triggers or waits on the `dte__<pipeline id>` DAGs.

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
