"""Dashboard CRUD (plan 064).

Five routes and nothing else. A dashboard is layout: it holds tiles, each
naming a pipeline and a chart spec. The rows a tile draws come from
`GET /api/pipelines/{id}/preview`, which already compiles and executes
without reaching a writer — so there is deliberately **no
`/dashboards/{id}/data`**. Fetching per tile costs one request each and
buys per-tile loading and error states for free; a batched route would have
to invent its own partial-failure shape.

Nothing here validates `tile.pipeline_id` against the pipeline store. A tile
pointing at a deleted pipeline renders "pipeline not found" in that tile
alone, which is visible and recoverable — see migration 038 for why the
reference cannot be a foreign key.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from dte.api.deps import get_dashboard_store
from dte.models.dashboard import DashboardBase
from dte.security.permissions import requires
from dte.store.base import DashboardStore

router = APIRouter()


@router.post("/dashboards", status_code=201, dependencies=[Depends(requires("dashboard:write"))])
async def create_dashboard(
    dashboard: DashboardBase,
    store: DashboardStore = Depends(get_dashboard_store),
):
    if await store.get(dashboard.id):
        raise HTTPException(
            status_code=409, detail=f"Dashboard '{dashboard.id}' already exists"
        )
    try:
        await store.save(dashboard)
    except ValueError as e:  # UNIQUE (name)
        raise HTTPException(status_code=409, detail=str(e))
    return dashboard.model_dump()


@router.get("/dashboards", dependencies=[Depends(requires("dashboard:read"))])
async def list_dashboards(
    limit: int = 50,
    offset: int = 0,
    store: DashboardStore = Depends(get_dashboard_store),
):
    rows = await store.list(limit=limit, offset=offset)
    return [r.model_dump() for r in rows]


@router.get("/dashboards/{dashboard_id}", dependencies=[Depends(requires("dashboard:read"))])
async def get_dashboard(
    dashboard_id: str,
    store: DashboardStore = Depends(get_dashboard_store),
):
    row = await store.get(dashboard_id)
    if not row:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return row.model_dump()


@router.put("/dashboards/{dashboard_id}", dependencies=[Depends(requires("dashboard:write"))])
async def update_dashboard(
    dashboard_id: str,
    dashboard: DashboardBase,
    store: DashboardStore = Depends(get_dashboard_store),
):
    if dashboard.id != dashboard_id:
        raise HTTPException(
            status_code=400, detail="Dashboard id in path and body must match"
        )
    if not await store.get(dashboard_id):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    try:
        await store.save(dashboard)
    except ValueError as e:  # UNIQUE (name)
        raise HTTPException(status_code=409, detail=str(e))
    return dashboard.model_dump()


@router.delete(
    "/dashboards/{dashboard_id}",
    status_code=204,
    dependencies=[Depends(requires("dashboard:delete"))],
)
async def delete_dashboard(
    dashboard_id: str,
    store: DashboardStore = Depends(get_dashboard_store),
):
    if not await store.get(dashboard_id):
        raise HTTPException(status_code=404, detail="Dashboard not found")
    await store.delete(dashboard_id)
    return Response(status_code=204)
