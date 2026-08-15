"""Recurring-trigger CRUD (plan 047 task 3).

Permissions reuse the existing ladder — scheduling is triggering on a
timer, not a new authority: `pipeline:read` to list/get, `pipeline:trigger`
to create/update/delete.

Cron and param validation both happen here, at write time, not at 2am:
- `cron_expr`/`timezone` are fed through `next_fire_after` — a bad cron or
  an unknown IANA zone name 422s immediately (`InvalidCronExpression` /
  `InvalidTimezone` from `dte.scheduling.cron`).
- `params` are run through the same `resolve_context` the trigger route
  uses, so a schedule missing a required declared param (no default) 422s
  at save time instead of failing silently every night — the exact
  scenario plan 047 calls out under "params validated at create time, not
  at 2am". Only the raw user-supplied values are stored; `{{now}}`/
  `{{today}}` still resolve at fire time.

`next_run_at` is always recomputed here (create and update) rather than
trusted from the request body — it's ticker-owned bookkeeping, not
something a client sets directly. A disabled schedule gets `next_run_at =
None` so re-enabling it later can't fire on a stale, long-past timestamp.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from dte.api.deps import get_eval_set_store, get_pipeline_store, get_schedule_store
from dte.compiler.interpolate import ParamValidationError, resolve_context
from dte.models.pipeline import ScheduleBase
from dte.scheduling.cron import InvalidCronExpression, InvalidTimezone, next_fire_after
from dte.security.permissions import requires
from dte.store.base import PipelineStore, ScheduleStore

router = APIRouter()


class ScheduleWriteRequest(BaseModel):
    """Shared shape for POST (create) and PUT (full replace) bodies.
    `pipeline_id` isn't here — it's the path param on create and immutable
    on update; ticker-owned fields (`next_run_at`, `last_run_id`,
    `last_fired_at`) aren't client-settable either."""

    id: str | None = None
    cron_expr: str
    timezone: str = "UTC"
    params: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    overlap: Literal["skip", "allow"] = "skip"
    eval_set_id: str | None = None


async def _validate_eval_set(pipeline, eval_set_id: str | None, es_store) -> None:
    """Same three rules the trigger route enforces, applied at save time.

    A schedule is a trigger on a timer. If the two paths disagree about
    what a valid eval run looks like, the disagreement surfaces at 2am
    with nobody watching — which is precisely the failure mode plan 047
    calls out for params and that plan 051 inherits.
    """
    ptype = getattr(pipeline, "pipeline_type", "transform") or "transform"
    if ptype == "eval" and not eval_set_id:
        raise HTTPException(
            status_code=422,
            detail="eval pipelines must be scheduled with an eval_set_id — "
                   "a scheduled eval run with no corpus scores nothing",
        )
    if eval_set_id and ptype != "eval":
        raise HTTPException(
            status_code=422,
            detail=f"eval_set_id is only valid for eval pipelines (this one is {ptype!r})",
        )
    # Resolved here rather than at fire time: a typo'd id would otherwise
    # persist happily and fail once a night, forever.
    if eval_set_id and not await es_store.get(eval_set_id):
        raise HTTPException(
            status_code=422, detail=f"eval set not found: {eval_set_id}"
        )


def _compute_next_run_at(cron_expr: str, tz_name: str, enabled: bool) -> datetime | None:
    if not enabled:
        return None
    try:
        return next_fire_after(cron_expr, tz_name, datetime.now(UTC))
    except InvalidCronExpression as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_cron_expression", "message": str(e)},
        ) from e
    except InvalidTimezone as e:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_timezone", "message": str(e)},
        ) from e


def _validate_params(pipeline, params: dict[str, str]) -> None:
    try:
        resolve_context(pipeline, params)
    except ParamValidationError as e:
        raise HTTPException(status_code=422, detail=e.payload()) from e


@router.post(
    "/pipelines/{pipeline_id}/schedules",
    dependencies=[Depends(requires("pipeline:trigger"))],
)
async def create_schedule(
    pipeline_id: str,
    body: ScheduleWriteRequest,
    p_store: PipelineStore = Depends(get_pipeline_store),
    sch_store: ScheduleStore = Depends(get_schedule_store),
    es_store=Depends(get_eval_set_store),
):
    pipeline = await p_store.get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    next_run_at = _compute_next_run_at(body.cron_expr, body.timezone, body.enabled)
    _validate_params(pipeline, body.params)
    await _validate_eval_set(pipeline, body.eval_set_id, es_store)

    schedule = ScheduleBase(
        id=body.id or str(_uuid.uuid4()),
        pipeline_id=pipeline_id,
        cron_expr=body.cron_expr,
        timezone=body.timezone,
        params=body.params,
        enabled=body.enabled,
        overlap=body.overlap,
        next_run_at=next_run_at,
        eval_set_id=body.eval_set_id,
    )
    await sch_store.save(schedule)
    return schedule


@router.get(
    "/pipelines/{pipeline_id}/schedules",
    dependencies=[Depends(requires("pipeline:read"))],
)
async def list_schedules_for_pipeline(
    pipeline_id: str,
    p_store: PipelineStore = Depends(get_pipeline_store),
    sch_store: ScheduleStore = Depends(get_schedule_store),
):
    if not await p_store.get(pipeline_id):
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return await sch_store.list_for_pipeline(pipeline_id)


@router.get("/schedules/{schedule_id}", dependencies=[Depends(requires("pipeline:read"))])
async def get_schedule(
    schedule_id: str,
    sch_store: ScheduleStore = Depends(get_schedule_store),
):
    schedule = await sch_store.get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.put("/schedules/{schedule_id}", dependencies=[Depends(requires("pipeline:trigger"))])
async def update_schedule(
    schedule_id: str,
    body: ScheduleWriteRequest,
    p_store: PipelineStore = Depends(get_pipeline_store),
    sch_store: ScheduleStore = Depends(get_schedule_store),
    es_store=Depends(get_eval_set_store),
):
    existing = await sch_store.get(schedule_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Schedule not found")
    pipeline = await p_store.get(existing.pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    next_run_at = _compute_next_run_at(body.cron_expr, body.timezone, body.enabled)
    _validate_params(pipeline, body.params)
    await _validate_eval_set(pipeline, body.eval_set_id, es_store)

    updated = ScheduleBase(
        id=schedule_id,
        pipeline_id=existing.pipeline_id,
        cron_expr=body.cron_expr,
        timezone=body.timezone,
        params=body.params,
        enabled=body.enabled,
        overlap=body.overlap,
        next_run_at=next_run_at,
        last_run_id=existing.last_run_id,
        last_fired_at=existing.last_fired_at,
        tenant_id=existing.tenant_id,
        eval_set_id=body.eval_set_id,
    )
    await sch_store.save(updated)
    return updated


@router.delete(
    "/schedules/{schedule_id}",
    status_code=204,
    dependencies=[Depends(requires("pipeline:trigger"))],
)
async def delete_schedule(
    schedule_id: str,
    sch_store: ScheduleStore = Depends(get_schedule_store),
):
    if not await sch_store.get(schedule_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    await sch_store.delete(schedule_id)
    return Response(status_code=204)
