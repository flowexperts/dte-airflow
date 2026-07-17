from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends, Response

from dte.models.pipeline import DestinationBase
from dte.api.deps import get_destination_store, get_pipeline_store
from dte.store.base import DestinationStore, PipelineStore

router = APIRouter()


@router.post("/destinations", status_code=201)
async def create_destination(
    destination: DestinationBase,
    store: DestinationStore = Depends(get_destination_store),
):
    if await store.get(destination.id):
        raise HTTPException(status_code=409, detail=f"Destination '{destination.id}' already exists")
    await store.save(destination)
    return destination.to_api_dict()


@router.get("/destinations")
async def list_destinations(limit: int = 50, offset: int = 0, store: DestinationStore = Depends(get_destination_store)):
    items = await store.list(limit=limit, offset=offset)
    return [d.to_api_dict() for d in items]


@router.get("/destinations/{destination_id}")
async def get_destination(destination_id: str, store: DestinationStore = Depends(get_destination_store)):
    d = await store.get(destination_id)
    if not d:
        raise HTTPException(status_code=404, detail="Destination not found")
    return d.to_api_dict()


@router.put("/destinations/{destination_id}")
async def update_destination(
    destination_id: str,
    destination: DestinationBase,
    store: DestinationStore = Depends(get_destination_store),
):
    if destination.id != destination_id:
        raise HTTPException(status_code=400, detail="Destination id in path and body must match")
    if not await store.get(destination_id):
        raise HTTPException(status_code=404, detail="Destination not found")
    await store.save(destination)
    return destination.to_api_dict()


@router.delete("/destinations/{destination_id}", status_code=204)
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
