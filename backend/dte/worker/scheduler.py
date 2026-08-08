"""The schedule ticker — the one code-defined periodic task in the
codebase (plan 047 task 5).

DTE's schedules are user-defined rows created through the API, not
code-defined `@app.periodic` decorators — you can't register a decorator
per row without restarting every worker on every customer edit. So there
is exactly one code-defined periodic task, `tick` (registered in
`dte.worker.app`), which reads the user data: `run_tick` queries
`ScheduleStore.list_due(now)` and, for each due schedule, either defers an
`execute_run` job (via `dte.worker.tasks.enqueue_run`, carrying
`schedule_id` so the run row records "fired because it was 2am") or
records an overlap-skip, then always advances `next_run_at` to the
schedule's next occurrence.

Procrastinate's periodic-defer mechanism dedups on
`(task_name, periodic_id, defer_timestamp)` — see the
`procrastinate_periodic_defers_unique` constraint in its schema — so only
one worker across the whole pool actually runs `tick` for a given minute,
even with N worker replicas all polling. That is the leader election plan
045 was going to hand-roll with `pg_try_advisory_lock`.

`run_tick` takes plain store arguments and no procrastinate-specific
context, so it's testable as an ordinary async function — see
`tests/unit/test_scheduler_tick.py`.
"""
from __future__ import annotations

from datetime import UTC, datetime

from dte.compiler.interpolate import ParamValidationError, resolve_context
from dte.logging import get_logger
from dte.scheduling.cron import next_fire_after
from dte.store.base import PipelineRevisionStore, PipelineStore, RunStore, ScheduleStore
from dte.worker.tasks import enqueue_run

_log = get_logger("dte.worker.scheduler")

TICK_TASK_NAME = "scheduler_tick"

# A tick that's due but more than this many seconds late is skipped rather
# than fired — firing a 2am nightly job at 11am is usually worse than not
# firing it at all. See plan 047, "Grace period".
GRACE_SECONDS_DEFAULT = 900

_IN_FLIGHT_STATUSES = frozenset({"pending", "running"})


async def run_tick(
    *,
    sch_store: ScheduleStore,
    r_store: RunStore,
    p_store: PipelineStore,
    rev_store: PipelineRevisionStore,
    now: datetime | None = None,
    grace_seconds: int = GRACE_SECONDS_DEFAULT,
) -> None:
    """One ticker pass over every due schedule, across every tenant.

    A single misbehaving schedule (bad pipeline reference, param that no
    longer validates because the pipeline changed since the schedule was
    saved, etc.) is logged at ERROR and skipped — it must never stop the
    rest of the tenants' schedules from firing.
    """
    if now is None:
        now = datetime.now(UTC)
    for schedule in await sch_store.list_due(now):
        try:
            await _fire_or_skip(
                schedule, sch_store=sch_store, r_store=r_store,
                p_store=p_store, rev_store=rev_store,
                now=now, grace_seconds=grace_seconds,
            )
        except Exception:
            _log.exception(
                "schedule tick failed — skipping this schedule, not the whole pass",
                extra={"schedule_id": schedule.id, "pipeline_id": schedule.pipeline_id},
            )


async def _fire_or_skip(
    schedule, *, sch_store, r_store, p_store, rev_store, now, grace_seconds,
) -> None:
    next_run_at = next_fire_after(schedule.cron_expr, schedule.timezone, now)

    age_seconds = (now - schedule.next_run_at).total_seconds()
    if age_seconds > grace_seconds:
        _log.warning(
            "schedule tick skipped: grace period exceeded",
            extra={
                "schedule_id": schedule.id, "pipeline_id": schedule.pipeline_id,
                "age_seconds": age_seconds,
            },
        )
        await sch_store.advance(schedule.id, next_run_at=next_run_at)
        return

    if schedule.overlap == "skip" and schedule.last_run_id:
        last_run = await r_store.get(schedule.last_run_id)
        if last_run and last_run.get("status") in _IN_FLIGHT_STATUSES:
            _log.info(
                "schedule tick skipped: previous run still in flight",
                extra={
                    "schedule_id": schedule.id,
                    "last_run_id": schedule.last_run_id,
                },
            )
            await sch_store.advance(schedule.id, next_run_at=next_run_at)
            return

    pipeline = await p_store.get(schedule.pipeline_id)
    if pipeline is None:
        # Shouldn't normally happen — ON DELETE CASCADE removes the
        # schedule with its pipeline — but a schedule must never wedge the
        # rest of the tick on a stale reference.
        _log.error(
            "schedule tick failed: pipeline not found",
            extra={"schedule_id": schedule.id, "pipeline_id": schedule.pipeline_id},
        )
        await sch_store.advance(schedule.id, next_run_at=next_run_at)
        return

    try:
        # {{now}}/{{today}} resolve fresh at fire time, not at schedule-save
        # time — only the user-supplied param values are stored on the
        # schedule row (plan 047).
        run_context = resolve_context(pipeline, schedule.params)
    except ParamValidationError:
        _log.exception(
            "schedule tick failed: params no longer valid for this pipeline",
            extra={"schedule_id": schedule.id, "pipeline_id": schedule.pipeline_id},
        )
        await sch_store.advance(schedule.id, next_run_at=next_run_at)
        return

    revision = await rev_store.latest_for_pipeline(schedule.pipeline_id)
    revision_id = revision.id if revision else None

    run_id, _job_id = await enqueue_run(
        schedule.pipeline_id, revision_id,
        tenant_id=schedule.tenant_id, schedule_id=schedule.id,
    )
    await r_store.update(run_id, params=run_context)
    await sch_store.advance(
        schedule.id, next_run_at=next_run_at,
        last_run_id=run_id, last_fired_at=now,
    )
    _log.info(
        "schedule fired",
        extra={"schedule_id": schedule.id, "pipeline_id": schedule.pipeline_id, "run_id": run_id},
    )


async def tick_task(timestamp: int) -> None:
    """Procrastinate periodic-task entrypoint — registered as
    `@app.periodic(cron="* * * * *")` on `dte.worker.app`'s App (task 6
    gates this behind `DTE_SCHEDULES_ENABLED`). Builds the real
    Postgres-backed stores and delegates to `run_tick`.

    `timestamp` is the deferred period boundary procrastinate's periodic
    decorator passes as the mandatory first positional arg — unused here,
    `run_tick` computes its own `now` so the actual fire check uses the
    real wall clock rather than the (slightly earlier) period boundary.
    """
    from dte.api.deps import (
        get_pipeline_revision_store,
        get_pipeline_store,
        get_run_store,
        get_schedule_store,
    )
    from dte.config import get_settings

    await run_tick(
        sch_store=get_schedule_store(),
        r_store=get_run_store(),
        p_store=get_pipeline_store(),
        rev_store=get_pipeline_revision_store(),
        grace_seconds=get_settings().schedule_grace_seconds,
    )
