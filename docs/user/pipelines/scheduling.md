# Scheduling

DTE runs inside Airflow, and Airflow does the scheduling. Every pipeline is exactly one Airflow
DAG, `dte__<pipeline id>`, and a pipeline has at most one schedule: the cron of that DAG. Manual
and scheduled runs land in the same DAG, with the same run history, output and logs.

The schedule is part of the pipeline, so changing it is a pipeline revision like any other edit,
and every revision becomes a new Airflow DAG version (Airflow starts a new version once the
previous one has run). Each run executes, and records, the exact revision it was started
against.

## Creating one

Open a pipeline, find the **Schedule** panel, and choose **Set schedule**.

Pick how often:

| | Meaning |
| --- | --- |
| **Hourly** | Every hour, at the minute you choose |
| **Daily** | Once a day, at the time you choose |
| **Weekly** | Once a week, on the day and time you choose |
| **Custom** | A standard 5-field cron expression |

**Custom** is there for the ones that don't fit — `0 2 * * 1-5` for weekday-only, say.

The pipeline's DAG picks up the cron on Airflow's next dag-processor parse (a few seconds).

### Timezone

The picker defaults to **your browser's timezone**, not UTC. Daylight saving is handled by
Airflow's cron timetable.

### Parameters

If your pipeline declares parameters, the form asks for them. Any parameter that is required
and has no default **must** get a value here — DTE rejects the schedule at save time
otherwise, rather than failing every night.

`{{now}}` and `{{today}}` resolve when the pipeline *runs*, not when you save the schedule.

## Checking it works

The panel shows the schedule's **next run time**. Runs started by a schedule are marked
**Scheduled** in the run list. The DAG, its next run and every task log are also visible in
the Airflow UI (filter by the `dte` tag).

## Rules worth knowing

**Missed runs are not made up.** Schedule DAGs use `catchup=False`: if the scheduler is down
from 1am to 7am, a 2am daily schedule does not fire six times when it comes back.

**Overlapping runs are skipped by default.** With **Overlap** set to *Skip*, the DAG runs with
`max_active_runs=1`, so a new run waits until the previous one finishes. That includes manual
runs: they share the DAG, so a manual trigger queues behind a running scheduled one. Set
**Overlap** to *Allow* if your pipeline is safe to run concurrently.

**Disabling keeps the schedule.** A disabled schedule leaves the DAG manual-only. Deleting a
pipeline deletes its schedule.

## Failures

A failed scheduled run behaves like a manual one: it lands in run history with the error. DTE
does **not** retry it, because a pipeline that partly wrote to its destination isn't safe to
re-run unattended. Use Airflow's own alerting (email, callbacks) on the `dte` DAGs if you need
notifications.

## API

```
GET    /dte/api/pipelines/{id}/schedule    read (null when unscheduled)
PUT    /dte/api/pipelines/{id}/schedule    set or replace
DELETE /dte/api/pipelines/{id}/schedule    remove
```

Body: `cron_expr`, `timezone`, `params`, `enabled`, `overlap` (`skip` | `allow`), and
`eval_set_id` for eval pipelines. The schedule is also the `schedule` field of the pipeline
itself; a pipeline `PUT` that omits it keeps the current one. A bad cron
expression, an unknown timezone, or a missing required parameter returns 422 explaining which.

## Chaining

"Run B after A succeeds" is plain Airflow: write a DAG that triggers or depends on the
`dte__<pipeline id>` DAGs.
