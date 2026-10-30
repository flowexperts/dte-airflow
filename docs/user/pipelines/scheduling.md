# Scheduling

Airflow does the scheduling. A pipeline is one DAG, `dte__<pipeline id>`, and has at most one schedule: that DAG's cron. Manual and scheduled runs share the DAG, run history and logs.

The schedule is part of the pipeline, so changing it is a new revision (and a new Airflow DAG version). Each run records the revision it started against.

## Creating one

Open a pipeline, find the **Schedule** panel, choose **Set schedule**.

![Schedule panel](../assets/pipelines/schedule.png)

| | Meaning |
| --- | --- |
| **Hourly** | Every hour, at the minute you choose |
| **Daily** | Once a day, at the time you choose |
| **Weekly** | Once a week, on the day and time you choose |
| **Custom** | A standard 5-field cron expression, e.g. `0 2 * * 1-5` |

The DAG picks up the cron on the next dag-processor parse.

### Timezone

Defaults to **your browser's timezone**, not UTC. Airflow's cron timetable handles DST.

### Parameters

A required parameter with no default must get a value here; the schedule is rejected at save otherwise. `{{now}}` and `{{today}}` resolve when the pipeline *runs*.

## Checking it

The panel shows the **next run time**. Scheduled runs are marked **Scheduled** in the run list, and the DAG is in Airflow (tag `dte`).

## Rules

- Missed runs aren't made up (`catchup=False`).
- Overlapping runs are skipped by default. **Overlap** *Skip* sets `max_active_runs=1`. Manual runs share the DAG, so a manual trigger queues behind a running scheduled one. Set *Allow* if concurrent runs are safe.
- Disabling keeps the schedule and leaves the DAG manual-only. Deleting a pipeline deletes its schedule.

## Failures

A failed scheduled run lands in run history with the error. dte does not retry, because a partly written destination isn't safe to re-run unattended. Use Airflow's alerting (email, callbacks) on the `dte` DAGs.

## API

```
GET    /dte/api/pipelines/{id}/schedule    read (null when unscheduled)
PUT    /dte/api/pipelines/{id}/schedule    set or replace
DELETE /dte/api/pipelines/{id}/schedule    remove
```

Body: `cron_expr`, `timezone`, `params`, `enabled`, `overlap` (`skip` | `allow`), and `eval_set_id` for eval pipelines. The schedule is also the `schedule` field of the pipeline; a pipeline `PUT` that omits it keeps the current one. A bad cron, unknown timezone or missing required parameter returns 422 with the reason.

## Chaining

"Run B after A" is plain Airflow: a DAG that triggers or depends on the `dte__<pipeline id>` DAGs.
