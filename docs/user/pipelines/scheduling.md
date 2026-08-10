# Scheduling

A schedule runs one pipeline on a repeating clock. Everything a manual trigger does, a
schedule does — same run history, same output, same error reporting.

Schedules are off unless your operator has enabled them. If you don't see a **Schedules**
panel on a pipeline, see [enabling schedules](#enabling-schedules) below.

## Creating one

Open a pipeline, find the **Schedules** panel, and add a schedule.

Pick how often:

| | Meaning |
| --- | --- |
| **Hourly** | Every hour, at the minute you choose |
| **Daily** | Once a day, at the time you choose |
| **Weekly** | Once a week, on the day and time you choose |
| **Custom** | A standard 5-field cron expression |

Most schedules need one of the first three. **Custom** is there for the ones that don't —
`0 2 * * 1-5` for weekday-only, say — and it accepts standard 5-field cron.

### Timezone

The picker defaults to **your browser's timezone**, not UTC. Check it before saving if your
team is spread across zones — "2am" means 2am somewhere specific.

Daylight saving is handled for you. On a spring-forward day, a schedule set for a time that
doesn't exist runs once at the next valid time. On a fall-back day, one that would happen
twice runs on the first occurrence only.

### Parameters

If your pipeline declares parameters, the form asks for them. Any parameter that is required
and has no default **must** get a value here — otherwise the schedule would fail every night
and you'd only find out from an empty destination. dte rejects the schedule at save time
instead.

`{{now}}` and `{{today}}` still resolve when the pipeline *runs*, not when you save the
schedule. A schedule using `{{today}}` gets today's date on every run.

## Checking it works

The panel shows the **next run time** for each schedule. This is the fastest way to confirm a
cron expression means what you think — set it, read the next fire time, adjust.

Runs started by a schedule are marked **Scheduled** in the run list, so you can tell them from
runs someone triggered by hand.

## Rules worth knowing

**Missed runs are not made up.** If dte is down from 1am to 7am, a 2am daily schedule does not
fire six times when it comes back. It skips to the next scheduled slot. This is deliberate —
replaying a backlog into a destination usually does more damage than the missed run did.

**Very late runs are skipped.** A run more than 15 minutes past its slot is skipped rather
than started, on the grounds that a 2am job starting at 11am is usually worse than not
starting. Your operator can change this window.

**Overlapping runs are skipped by default.** If the previous run of a schedule is still going
when the next is due, dte skips the new one rather than running both. A nightly job that
starts taking 25 hours won't pile up. Set **Overlap** to *Allow* if your pipeline is safe to
run concurrently.

**Disabling keeps the schedule.** The toggle stops it firing without deleting it. Deleting a
pipeline deletes its schedules.

## Failures

A scheduled run that fails behaves exactly like a manual one — it lands in run history with
the error. dte does **not** retry it, because a pipeline that partly wrote to its destination
isn't safe to re-run unattended.

There's no per-schedule email or alert yet. Watch run history, or poll
`GET /api/pipelines/{id}/runs`.

## Enabling schedules

For operators. Schedules need distributed execution, so both flags go on:

```yaml
DTE_JOB_QUEUE_ENABLED: "true"
DTE_SCHEDULES_ENABLED: "true"
```

Set them on the `worker` service (the ticker runs there) and the `backend` service. At least
one worker must be running — see [Scaling and execution](../self-hosting/scaling.md).

`DTE_SCHEDULE_GRACE_SECONDS` (default `900`) is the late-run window described above.

A worker checks for due schedules once a minute. Running several workers is safe: exactly one
picks up each tick.

## API

```
POST   /api/pipelines/{id}/schedules   create
GET    /api/pipelines/{id}/schedules   list for a pipeline
GET    /api/schedules/{id}             read
PUT    /api/schedules/{id}             update
DELETE /api/schedules/{id}             delete
```

Body: `cron_expr`, `timezone`, `params`, `enabled`, `overlap` (`skip` | `allow`). A bad cron
expression, an unknown timezone, or a missing required parameter returns 422 explaining which.

## Not supported

- **Chaining** — "run B after A succeeds". dte runs pipelines; it doesn't orchestrate between
  them. Point Airflow, Prefect, or Dagster at the trigger API for that.
- **Sub-minute schedules.** One minute is the floor.
- **Backfill.** Covered above — missed slots are skipped, not replayed.
