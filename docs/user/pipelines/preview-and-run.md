# Preview & run

Two feedback loops. Use them together.

## Preview

The pipeline page shows a **Preview**: dte runs your steps on a small sample and shows the result as a table.

- It's always safe. Preview **reads** sources and never writes to a destination.
- The sample size is capped at about 20 rows. Preview shows the *shape* of the output, not row totals.
- If a step is broken (a bad type cast, a missing field, an invalid filter), the panel goes red and shows what went wrong. Fix it and preview again. This is the fastest way to debug in dte.

Preview runs in Airflow's api-server, not as an Airflow task, so it doesn't appear in run history.

## Run

**▶ Run** starts a real run. If the pipeline declares parameters, dte asks for them first. The run is an Airflow dag run of `dte__<pipeline id>`: Airflow's scheduler queues it and an Airflow worker executes it.

The run appears on the pipeline page straight away, and you watch it there.

## What a run shows

The run refreshes every couple of seconds until it finishes. You see:

- **Status**: `pending` → `running` → `completed` or `failed` (see [run statuses](../getting-started/03-concepts.md#run))
- **Rows written**
- **Elapsed**: how long the run took
- **Started**
- **Trigger params**, if the pipeline has parameters
- **Quality checks**, if the pipeline has any, each passed or failed
- On failure: the error, in full

The same dag run is in Airflow, with the task log, under the `dte__<pipeline id>` DAG. Filter the DAG list by the `dte` tag to see them all.

## Peek at the output

For file destinations, the run page shows the first rows of the written file, so you can spot-check without leaving dte.

## Cancel

dte has no cancel button yet. Mark the dag run failed in Airflow, or call `POST /dte/api/runs/{run_id}/cancel`, and Airflow stops the running task.

## Run history

The pipeline's **Runs** tab lists every run, marked **Manual** or **Scheduled**.
