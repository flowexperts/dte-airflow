"""Pipeline notifications (plan 070): `GET/PUT /pipelines/{id}/notifications`
and the notifier catalogue, `GET /notifiers`.

A notification is any notifier an installed Airflow provider registers, fired
on the pipeline's run events, manual and scheduled alike. It's part of the
pipeline spec, so a change is a revision and so a new DAG version. Each one is
checked at save: registered class, constructor args that bind, and any
`*_conn_id` naming an Airflow connection that exists.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from dte.api.deps import get_current_user, get_pipeline_revision_store, get_pipeline_store
from dte.api.routes.schedules import _load, _save
from dte.models.pipeline import PipelineNotification
from dte.models.user import User
from dte.security.permissions import requires
from dte.store.base import PipelineRevisionStore, PipelineStore

router = APIRouter()


async def validate_notifications(notifications: list[PipelineNotification]) -> None:
    from dte.airflow import notify

    for i, n in enumerate(notifications):
        if problem := await asyncio.to_thread(notify.problem, n.model_dump()):
            raise HTTPException(status_code=422, detail={
                "code": "invalid_notification", "index": i, "message": problem})


@router.get("/notifiers", dependencies=[Depends(requires("pipeline:read"))])
async def list_notifiers():
    from dte.airflow import notify

    def _all():
        out = []
        for path in notify.available_notifiers():
            try:
                out.append(notify.describe(path))
            except Exception:  # a provider whose deps aren't installed
                continue
        return out
    return await asyncio.to_thread(_all)


@router.get("/pipelines/{pipeline_id}/notifications", dependencies=[Depends(requires("pipeline:read"))])
async def get_notifications(pipeline_id: str, p_store: PipelineStore = Depends(get_pipeline_store)):
    return (await _load(pipeline_id, p_store)).notifications


@router.put("/pipelines/{pipeline_id}/notifications", dependencies=[Depends(requires("pipeline:write"))])
async def put_notifications(
    pipeline_id: str,
    body: list[PipelineNotification],
    p_store: PipelineStore = Depends(get_pipeline_store),
    rev_store: PipelineRevisionStore = Depends(get_pipeline_revision_store),
    user: User = Depends(get_current_user),
):
    pipeline = await _load(pipeline_id, p_store)
    await validate_notifications(body)
    pipeline.notifications = body
    await _save(pipeline, p_store, rev_store, user)
    return body
