"""A pipeline's one schedule (plan 068): `GET/PUT/DELETE /pipelines/{id}/schedule`.

The schedule is part of the pipeline spec, so every change here is a pipeline
save plus a revision — and a revision is what becomes the DAG version
(`dte.airflow.dag_factory`). Permissions: `pipeline:read` to read,
`pipeline:trigger` to change, as scheduling is triggering on a timer.

Validation happens at save time, not at 2am, and is shared with the pipeline
POST/PUT via `validate_schedule`:
- `cron_expr`/`timezone` go through `next_fire_after`, so a bad cron or an
  unknown IANA zone 422s immediately.
- `params` go through the trigger route's `resolve_context`, so a missing
  required param 422s. Only raw values are stored; `{{now}}`/`{{today}}`
  resolve at fire time.
- `eval_set_id` follows the trigger route's eval rules.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response

from dte.api.deps import get_current_user, get_destination_store, get_eval_set_store, get_pipeline_revision_store, get_pipeline_store
from dte.compiler.interpolate import ParamValidationError, resolve_context
from dte.models.pipeline import Pipeline, PipelineBase, PipelineSchedule
from dte.models.user import User
from dte.scheduling.cron import InvalidCronExpression, InvalidTimezone, next_fire_after
from dte.security.permissions import requires
from dte.store.base import PipelineRevisionStore, PipelineStore

router = APIRouter()


def _next_run_at(sc: PipelineSchedule) -> datetime | None:
    if not sc.enabled:
        return None
    try:
        return next_fire_after(sc.cron_expr, sc.timezone, datetime.now(UTC))
    except InvalidCronExpression as e:
        raise HTTPException(status_code=422, detail={"code": "invalid_cron_expression", "message": str(e)}) from e
    except InvalidTimezone as e:
        raise HTTPException(status_code=422, detail={"code": "invalid_timezone", "message": str(e)}) from e


async def validate_schedule(pipeline: PipelineBase, es_store, d_store) -> None:
    """422 unless `pipeline.schedule` (if any) can actually fire."""
    sc = pipeline.schedule
    if sc is None:
        return
    _next_run_at(sc)
    try:
        resolve_context(pipeline, sc.params)
    except ParamValidationError as e:
        raise HTTPException(status_code=422, detail=e.payload()) from e
    ptype = pipeline.pipeline_type or "transform"
    if ptype == "eval" and not sc.eval_set_id:
        raise HTTPException(status_code=422, detail="eval pipelines must be scheduled with an eval_set_id — "
                                                    "a scheduled eval run with no corpus scores nothing")
    if sc.eval_set_id and ptype != "eval":
        raise HTTPException(status_code=422,
                            detail=f"eval_set_id is only valid for eval pipelines (this one is {ptype!r})")
    if sc.eval_set_id and not await es_store.get(sc.eval_set_id):
        raise HTTPException(status_code=422, detail=f"eval set not found: {sc.eval_set_id}")
    # ponytail: checked at schedule save only; switching the destination to
    # append later isn't re-checked. Move to the operator if that bites.
    if sc.retries and pipeline.output_id:
        dest = await d_store.get(pipeline.output_id)
        cfg = dest.config if dest else None  # a dict or an already-narrowed target model
        wd = cfg.get("write_disposition") if isinstance(cfg, dict) else getattr(cfg, "write_disposition", None)
        if wd == "append":
            raise HTTPException(status_code=422, detail={
                "code": "retries_on_append",
                "message": "retries are off for append destinations: a retry after a partial write duplicates rows"})


def _out(sc: PipelineSchedule | None) -> dict | None:
    if sc is None:
        return None
    try:
        nxt = _next_run_at(sc)
    except HTTPException:
        nxt = None
    return {**sc.model_dump(), "next_run_at": nxt}


async def _load(pipeline_id: str, p_store: PipelineStore) -> PipelineBase:
    row = await p_store.get(pipeline_id)
    if not row:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return PipelineBase.model_validate(row.model_dump())


async def _save(pipeline: PipelineBase, p_store, rev_store, user) -> None:
    from dte.api.routes.pipelines import _record_revision

    await p_store.save(Pipeline(**pipeline.model_dump()))
    await _record_revision(pipeline, rev_store, user)


@router.get("/pipelines/{pipeline_id}/schedule", dependencies=[Depends(requires("pipeline:read"))])
async def get_schedule(pipeline_id: str, p_store: PipelineStore = Depends(get_pipeline_store)):
    return _out((await _load(pipeline_id, p_store)).schedule)


@router.put("/pipelines/{pipeline_id}/schedule", dependencies=[Depends(requires("pipeline:trigger"))])
async def put_schedule(
    pipeline_id: str,
    body: PipelineSchedule,
    p_store: PipelineStore = Depends(get_pipeline_store),
    rev_store: PipelineRevisionStore = Depends(get_pipeline_revision_store),
    es_store=Depends(get_eval_set_store),
    d_store=Depends(get_destination_store),
    user: User = Depends(get_current_user),
):
    pipeline = await _load(pipeline_id, p_store)
    pipeline.schedule = body
    await validate_schedule(pipeline, es_store, d_store)
    await _save(pipeline, p_store, rev_store, user)
    return _out(body)


@router.delete(
    "/pipelines/{pipeline_id}/schedule", status_code=204,
    dependencies=[Depends(requires("pipeline:trigger"))],
)
async def delete_schedule(
    pipeline_id: str,
    p_store: PipelineStore = Depends(get_pipeline_store),
    rev_store: PipelineRevisionStore = Depends(get_pipeline_revision_store),
    user: User = Depends(get_current_user),
):
    pipeline = await _load(pipeline_id, p_store)
    if pipeline.schedule is not None:
        pipeline.schedule = None
        await _save(pipeline, p_store, rev_store, user)
    return Response(status_code=204)
