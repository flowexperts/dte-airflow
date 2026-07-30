# FAQ

## Can I schedule a pipeline to run automatically?

Not yet from inside dte. Trigger it from your own scheduler (cron, Airflow, GitHub Actions) — hit the trigger endpoint on your dte instance. Scheduling from within the app is on the roadmap.

## Can I rename a pipeline id?

Not today. The id is used in URLs and run history, so it's fixed after creation. The **Name** field is free to change any time.

## Can two pipelines write to the same table?

Yes — but with a database destination, be careful about the write mode. Two pipelines both set to **Replace** will race each other on every run. **Append** or **Merge** are usually what you want.

## Can I edit a source without breaking pipelines that use it?

You can edit, but changes affect every pipeline that reads that source on the next run. The source form warns you.

If you need to change a source drastically, duplicate it, edit the copy, then switch pipelines one by one.

## What happens to a running pipeline if I edit it mid-run?

Nothing — the run is a snapshot. Your edits apply on the next trigger.

## Where does the output actually go?

Wherever the destination points. For file destinations, that's a folder on the machine dte runs on. Ask your admin if you're not sure where that is.

## Can I preview more than 20 rows?

Not from the UI. Preview is for shape, not scale — trigger a real run and peek at the output.

## The field picker is empty. Why?

You haven't run **Infer schema** on the source yet. Go to the source card and click it.

## How do I filter on a nested field?

Use dot syntax: `order.amount > 100`. See [Field names](pipelines/field-refs.md).

## Can I use a Google Sheet as a source?

Not directly. Export or sync the sheet to a database or CSV, then read that.

## Can I share a pipeline with a teammate?

Every user on the same dte instance sees the same pipelines. There's no per-pipeline sharing today.

## Is my data leaving the instance?

No. dte reads from your sources, transforms in place, and writes to your destinations. Nothing goes anywhere else.
