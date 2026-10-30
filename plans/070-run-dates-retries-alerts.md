# Plan 070: run dates from the run, plus retries and alerts

## Context
The question was what to improve next in Airflow + DTE. I surveyed the gaps in
`backend/dte/airflow/*`. Asset chaining and backfill are deferred; the user
picked these two:

1. **Bug: `{{today}}`, `{{yesterday}}` and the other date variables use the wall
   clock.** `compiler/interpolate.py:135` `_system_context()` calls `date.today()`.
   So a scheduled run that starts late, or is cleared and rerun in Airflow,
   processes the wrong day. Runs are not idempotent, and backfill is impossible
   later.
2. **No retries, no timeout, no alerts.** `DtePipelineOperator` uses Airflow's
   defaults: zero retries and no timeout. A transient S3 or DB blip fails the run,
   and nobody hears about it.

Implementation step 0: copy this file to `plans/070-run-dates-retries-alerts.md`.
Branch `feature/070-run-dates-retries-alerts` in `worktrees/070-run-dates-retries-alerts`.

## Part A: run dates

**`compiler/interpolate.py`**
- `_system_context(as_of: datetime | None = None)`: `now = as_of or datetime.now(utc)`
  and `today = now.date()`. The rest is unchanged.
- `resolve_context(pipeline, user_values, *, as_of=None)` passes `as_of` to
  `_system_context` **and** to `coerce_param_value(raw, t, as_of=as_of)`. Line 102
  resolves the `{{today}}` sentinels in param defaults, and those are the ones
  schedules use most.

**`airflow/operators.py:117`** (scheduled path only. Manual runs already carry a
`conf.context` pinned at trigger time, so a retry of a manual run is already
idempotent):
```python
as_of = context.get("logical_date")
if as_of is not None:
    as_of = as_of.in_timezone(rev.config.get("schedule", {}).get("timezone", "UTC"))  # pendulum
values = conf.get("context") or resolve_context(pipeline, user_params or None, as_of=as_of)
```
- `CronTriggerTimetable` makes `logical_date` the cron fire time. Converting it to
  the schedule's timezone means a `0 1 * * *` run in Asia/Kolkata gets the local
  date, not the UTC one.
- `logical_date` is None for manual runs (`trigger.py` sends `logical_date: None`),
  so they fall back to the wall clock, which is the current behaviour.

Other callers (`routes/pipelines.py` preview, trigger and validate;
`routes/schedules.py:52`; `runner.py:62`) don't change, because they mean "now".

## Part B: retries, timeout, alerts

**Model.** Add to `PipelineSchedule` (`models/pipeline.py:1285`). It is JSONB, so
there is no migration:
```python
retries: int = Field(0, ge=0, le=10)
retry_delay_s: int = Field(300, ge=10)
timeout_s: int | None = Field(None, ge=60)
notify_conn_id: str | None = None   # Airflow smtp or slackwebhook connection
```
`retries` defaults to **0** on purpose. Destinations with
`write_disposition="append"` (`models/pipeline.py:1034`) would duplicate rows if
an attempt fails after it has written. In `validate_schedule`
(`routes/schedules.py:45`), reject with 422 `retries > 0` when the destination is
append. Replace and merge are safe to retry: `record_result` upserts by `run_id`
(`airflow/results.py`).

**DAG factory** (`airflow/dag_factory.py:52`). Pass to the operator:
- `retries`
- `retry_delay=timedelta(seconds=...)`
- `execution_timeout=timedelta(seconds=timeout_s) if timeout_s else None`
- `on_failure_callback=notify_failure if sc.get("notify_conn_id") else None`

Existing behaviour already gives the retry semantics. `AirflowFailException`
(quality failure, missing revision/source/destination) never retries, and plain
exceptions do.

**Alerts: new `airflow/notify.py`** (about 20 lines). `notify_failure(context)`
reads `notify_conn_id` from the task's DAG schedule (passed as a `partial` arg).
It then picks a notifier from `BaseHook.get_connection(id).conn_type`:
`smtp` → `SmtpNotifier(to=conn.extra_dejson["to"], ...)`,
`slackwebhook` → `SlackWebhookNotifier(slack_webhook_conn_id=id, text=...)`.
The message is the pipeline name, run id, the error from `context["exception"]`
and a link to the Airflow grid. Any other conn type logs a warning. No DTE alert
store and no templates: the notifiers are Airflow's own.
- Check first that the `apache/airflow:3.3.2` image ships
  `apache-airflow-providers-smtp` and `-slack`. If a provider is missing, add it
  to the `pip install` line in `Dockerfile.airflow`.

**Frontend** (`components/builder/schedules/ScheduleForm.tsx`): add an "On
failure" section with Retries (number), Retry delay, Timeout and Notify
connection id. The connection id is a plain text input:
`ConnectionPicker` lists only DTE-mappable connections, so smtp and Slack
connections never appear in it. Show the 422 inline the way the cron errors are
shown. Regenerate the API types.

## Tests first (`backend/tests`)
- `unit/test_interpolate.py`: `resolve_context(as_of=datetime(2026,3,2,tzinfo=utc))`
  gives `today=2026-03-02`, `yesterday=2026-03-01` and `start_of_month=2026-03-01`.
  A param default `{{yesterday}}` resolves against `as_of`.
- Operator test (next to the existing plan-068 operator tests): fake context with
  `logical_date=2026-03-02T00:30Z` and schedule tz `Asia/Kolkata` gives
  `today=2026-03-02` in the interpolated filter. A filter with `{{yesterday}}`
  and a fixed logical date gives the same SQL on two executions.
- `dag_factory`: the schedule `retries=2, timeout_s=600` gives
  `task.retries == 2` and `task.execution_timeout == 600s`. `notify_conn_id`
  sets `on_failure_callback`.
- Schedule validation: `retries=1` with an append destination gives 422, and
  with a replace destination gives 200.
- `notify.py`: a fake smtp connection calls `SmtpNotifier` with the error text.
  An unknown conn type logs and does not raise.

## Files
Changed: `dte/compiler/interpolate.py`, `dte/airflow/operators.py`,
`dte/airflow/dag_factory.py`, `dte/models/pipeline.py`, `dte/api/routes/schedules.py`,
`frontend/src/components/builder/schedules/ScheduleForm.tsx`, the generated API
types, `docs/user/pipelines/scheduling.md`, and possibly `Dockerfile.airflow`.
New: `dte/airflow/notify.py`, plus the tests above.

## Verification
1. `cd worktrees/070-…/backend && uv run pytest -x` passes.
2. Compose (run from the worktree, per `docs/worktrees.md`): schedule a
   local_fs pipeline that filters on `{{yesterday}}`, let it fire, then **Clear**
   the run in Airflow the next day. The rerun's SQL in the run detail shows the
   original date.
3. Point a source at a missing S3 bucket with `retries=2`. The Airflow grid shows
   3 tries. A `fail` quality check shows 1 try.
4. Create an `smtp` connection (MailHog, or a Slack webhook) and set it as
   `notify_conn_id`. A failed run sends one message.

Deferred: Asset chaining (#3) and backfill (#2). Backfill becomes trivial after
Part A, because Airflow's `POST /api/v2/backfills` then produces correct dates.

## Revision: notifications are not part of the schedule

Review feedback: a schedule and a notification are different things. Manual runs
notify too, and a notification can be anything Airflow supports through providers.
So `notify_conn_id` and its smtp/Slack-only code were removed from the schedule, and:

- `pipeline.notifications: [{notifier, params, on}]` is a JSONB column (migration
  `041`) and part of every revision. `on` ⊆ failure | retry | success.
- `notifier` must be in `ProvidersManager().notification`. Only registered classes
  are imported, so a saved class path can't reach arbitrary code. `params` are the
  notifier's constructor kwargs. Templated ones can use `{{ dte_message }}` and
  `{{ dte_event }}`, which are passed as context variables, so error text is never
  itself rendered.
- Save-time check (`notify.problem`): the notifier is registered, `cls(**params)`
  binds, and every literal `*_conn_id` names an existing Airflow connection.
- Routes: `GET /api/notifiers`, `GET/PUT /api/pipelines/{id}/notifications`. A
  pipeline PUT that omits `notifications` keeps them.
- DAG factory: `notify.callbacks()` gives `on_<event>_callback` lists on the one
  task, so the callbacks fire for manual and scheduled runs alike.
- UI: a Notifications panel under Schedule. It has a notifier dropdown from
  `/api/notifiers`, event checkboxes, and a params JSON editor prefilled from the
  notifier's signature.

Retries and timeout stay on the schedule for now, even though they too apply to
manual runs.
