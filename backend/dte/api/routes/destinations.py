from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from dte.api.deps import get_destination_store, get_pipeline_store
from dte.models.pipeline import DestinationBase
from dte.security.permissions import requires
from dte.store.base import DestinationStore, PipelineStore

router = APIRouter()

BULK_DELETE_LIMIT = 200


class BulkDeleteRequest(BaseModel):
    ids: list[str] = Field(..., min_length=1, max_length=BULK_DELETE_LIMIT)


@router.post("/destinations", status_code=201, dependencies=[Depends(requires("destination:write"))])
async def create_destination(
    destination: DestinationBase,
    store: DestinationStore = Depends(get_destination_store),
):
    if await store.get(destination.id):
        raise HTTPException(status_code=409, detail=f"Destination '{destination.id}' already exists")
    try:
        await store.save(destination)
    except ValueError as e:  # name collision
        raise HTTPException(status_code=409, detail=str(e))
    return destination.to_api_dict()


@router.get("/destinations", dependencies=[Depends(requires("destination:read"))])
async def list_destinations(limit: int = 50, offset: int = 0, store: DestinationStore = Depends(get_destination_store)):
    items = await store.list(limit=limit, offset=offset)
    return [d.to_api_dict() for d in items]


@router.get("/destinations/{destination_id}", dependencies=[Depends(requires("destination:read"))])
async def get_destination(destination_id: str, store: DestinationStore = Depends(get_destination_store)):
    d = await store.get(destination_id)
    if not d:
        raise HTTPException(status_code=404, detail="Destination not found")
    return d.to_api_dict()


@router.put("/destinations/{destination_id}", dependencies=[Depends(requires("destination:write"))])
async def update_destination(
    destination_id: str,
    destination: DestinationBase,
    store: DestinationStore = Depends(get_destination_store),
):
    if destination.id != destination_id:
        raise HTTPException(status_code=400, detail="Destination id in path and body must match")
    if not await store.get(destination_id):
        raise HTTPException(status_code=404, detail="Destination not found")
    try:
        await store.save(destination)
    except ValueError as e:  # name collision
        raise HTTPException(status_code=409, detail=str(e))
    return destination.to_api_dict()


@router.post("/destinations/bulk-delete", dependencies=[Depends(requires("destination:delete"))])
async def bulk_delete_destinations(
    body: BulkDeleteRequest,
    d_store: DestinationStore = Depends(get_destination_store),
    p_store: PipelineStore = Depends(get_pipeline_store),
):
    ids = list(dict.fromkeys(body.ids))
    pipelines = await p_store.list(limit=10_000)

    deleted: list[str] = []
    not_found: list[str] = []
    blocked: list[dict] = []
    for did in ids:
        if not await d_store.get(did):
            not_found.append(did)
            continue
        referenced_by = [p.id for p in pipelines if p.output_id == did]
        if referenced_by:
            blocked.append({"id": did, "referenced_by": referenced_by})
            continue
        await d_store.delete(did)
        deleted.append(did)
    return {"deleted": deleted, "not_found": not_found, "blocked": blocked}


@router.delete("/destinations/{destination_id}", status_code=204, dependencies=[Depends(requires("destination:delete"))])
async def delete_destination(
    destination_id: str,
    d_store: DestinationStore = Depends(get_destination_store),
    p_store: PipelineStore = Depends(get_pipeline_store),
):
    if not await d_store.get(destination_id):
        raise HTTPException(status_code=404, detail="Destination not found")
    referenced_by = [
        p.id for p in await p_store.list(limit=10_000)
        if p.output_id == destination_id
    ]
    if referenced_by:
        raise HTTPException(status_code=409, detail={"referenced_by": referenced_by})
    await d_store.delete(destination_id)
    return Response(status_code=204)
