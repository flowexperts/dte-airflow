from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from dte.api.deps import get_lookup_table_store, get_pipeline_store
from dte.models.pipeline import LookupTableBase
from dte.security.permissions import requires
from dte.store.base import LookupTableStore, PipelineStore

router = APIRouter()

BULK_DELETE_LIMIT = 200


class BulkDeleteRequest(BaseModel):
    ids: list[str] = Field(..., min_length=1, max_length=BULK_DELETE_LIMIT)


def _referenced_by(pipelines, lookup_id: str) -> list[str]:
    refs = []
    for p in pipelines:
        for step in p.steps or []:
            if (
                step.get("op") == "map"
                and step.get("mode") == "lookup"
                and step.get("lookup_id") == lookup_id
            ):
                refs.append(p.id)
                break
    return refs


@router.post("/lookup-tables", status_code=201, dependencies=[Depends(requires("lookup_table:write"))])
async def create_lookup_table(
    lookup: LookupTableBase,
    store: LookupTableStore = Depends(get_lookup_table_store),
):
    if await store.get(lookup.id):
        raise HTTPException(
            status_code=409, detail=f"Lookup table '{lookup.id}' already exists"
        )
    try:
        await store.save(lookup)
    except ValueError as e:  # name collision
        raise HTTPException(status_code=409, detail=str(e))
    return lookup.model_dump()


@router.get("/lookup-tables", dependencies=[Depends(requires("lookup_table:read"))])
async def list_lookup_tables(
    limit: int = 50,
    offset: int = 0,
    store: LookupTableStore = Depends(get_lookup_table_store),
):
    rows = await store.list(limit=limit, offset=offset)
    return [r.model_dump() for r in rows]


@router.get("/lookup-tables/{lookup_id}", dependencies=[Depends(requires("lookup_table:read"))])
async def get_lookup_table(
    lookup_id: str,
    store: LookupTableStore = Depends(get_lookup_table_store),
):
    row = await store.get(lookup_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lookup table not found")
    return row.model_dump()


@router.put("/lookup-tables/{lookup_id}", dependencies=[Depends(requires("lookup_table:write"))])
async def update_lookup_table(
    lookup_id: str,
    lookup: LookupTableBase,
    store: LookupTableStore = Depends(get_lookup_table_store),
):
    if lookup.id != lookup_id:
        raise HTTPException(
            status_code=400, detail="Lookup id in path and body must match"
        )
    if not await store.get(lookup_id):
        raise HTTPException(status_code=404, detail="Lookup table not found")
    try:
        await store.save(lookup)
    except ValueError as e:  # name collision
        raise HTTPException(status_code=409, detail=str(e))
    return lookup.model_dump()


@router.post("/lookup-tables/bulk-delete", dependencies=[Depends(requires("lookup_table:delete"))])
async def bulk_delete_lookup_tables(
    body: BulkDeleteRequest,
    lt_store: LookupTableStore = Depends(get_lookup_table_store),
    p_store: PipelineStore = Depends(get_pipeline_store),
):
    ids = list(dict.fromkeys(body.ids))
    pipelines = await p_store.list(limit=10_000)
    deleted: list[str] = []
    not_found: list[str] = []
    blocked: list[dict] = []
    for lid in ids:
        if not await lt_store.get(lid):
            not_found.append(lid)
            continue
        refs = _referenced_by(pipelines, lid)
        if refs:
            blocked.append({"id": lid, "referenced_by": refs})
            continue
        await lt_store.delete(lid)
        deleted.append(lid)
    return {"deleted": deleted, "not_found": not_found, "blocked": blocked}


@router.delete("/lookup-tables/{lookup_id}", status_code=204, dependencies=[Depends(requires("lookup_table:delete"))])
async def delete_lookup_table(
    lookup_id: str,
    lt_store: LookupTableStore = Depends(get_lookup_table_store),
    p_store: PipelineStore = Depends(get_pipeline_store),
):
    if not await lt_store.get(lookup_id):
        raise HTTPException(status_code=404, detail="Lookup table not found")
    refs = _referenced_by(await p_store.list(limit=10_000), lookup_id)
    if refs:
        raise HTTPException(status_code=409, detail={"referenced_by": refs})
    await lt_store.delete(lookup_id)
    return Response(status_code=204)
