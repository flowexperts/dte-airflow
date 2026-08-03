from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from dte.api.deps import (
    get_connection_store,
    get_destination_store,
    get_source_store,
)
from dte.logging import decrypt_context_var
from dte.models.pipeline import Connection, ConnectionBase
from dte.security.permissions import requires
from dte.sources.connection_test import probe_connection
from dte.sources.pools import mongo as mongo_pool
from dte.store.base import ConnectionStore, DestinationStore, SourceStore

BULK_DELETE_LIMIT = 200


class BulkDeleteRequest(BaseModel):
    ids: list[str] = Field(..., min_length=1, max_length=BULK_DELETE_LIMIT)

router = APIRouter()


def _mask(c: Connection) -> dict:
    """Return a plain dict with credentials values replaced by '***'."""
    return {
        "id": c.id,
        "name": c.name or c.id,
        "connection_type": c.connection_type,
        "credentials": {k: "***" for k in c.credentials},
    }


@router.post("/connections", status_code=201, dependencies=[Depends(requires("connection:write"))])
async def create_connection(
    connection: ConnectionBase,
    store: ConnectionStore = Depends(get_connection_store),
):
    # If the client supplied an id (legacy), refuse if it's already taken.
    if await store.get(connection.id):
        raise HTTPException(status_code=409, detail=f"Connection '{connection.id}' already exists")
    try:
        await store.save(connection)
    except ValueError as e:  # name collision from FakeConnectionStore
        raise HTTPException(status_code=409, detail=str(e))
    return _mask_base(connection)


def _mask_base(connection: ConnectionBase) -> dict:
    """Mask credentials from a ConnectionBase (used for POST/PUT responses)."""
    creds = connection.credentials or {}
    return {
        "id": connection.id,
        "name": connection.name or connection.id,
        "connection_type": connection.connection_type,
        "credentials": {k: "***" for k in creds},
    }


@router.get("/connections", dependencies=[Depends(requires("connection:read"))])
async def list_connections(
    limit: int = 50,
    offset: int = 0,
    store: ConnectionStore = Depends(get_connection_store),
):
    connections = await store.list(limit=limit, offset=offset)
    return [_mask(c) for c in connections]


@router.get("/connections/{connection_id}", dependencies=[Depends(requires("connection:read"))])
async def get_connection(
    connection_id: str,
    reveal: bool = False,
    store: ConnectionStore = Depends(get_connection_store),
):
    decrypt_context_var.set("reveal_api" if reveal else "connection_read")
    c = await store.get(connection_id)
    if not c:
        raise HTTPException(status_code=404, detail="Connection not found")
    if reveal:
        # Reveal path is a deliberate escape hatch (e.g., the UI edit form
        # pre-populating fields). Callers should treat this as sensitive.
        return {
            "id": c.id,
            "name": c.name or c.id,
            "connection_type": c.connection_type,
            "credentials": c.credentials,
        }
    return _mask(c)


@router.put("/connections/{connection_id}", dependencies=[Depends(requires("connection:write"))])
async def update_connection(
    connection_id: str,
    connection: ConnectionBase,
    store: ConnectionStore = Depends(get_connection_store),
):
    existing = await store.get(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Connection not found")
    if connection.id != connection_id:
        raise HTTPException(status_code=400, detail="Connection id in path and body must match")
    # If credentials omitted (empty dict) on PUT, keep the existing set.
    if not connection.credentials:
        existing_creds = existing.credentials
        connection = ConnectionBase(
            id=connection.id,
            name=connection.name,
            connection_type=connection.connection_type,
            credentials=existing_creds,
        )
    try:
        await store.save(connection)
    except ValueError as e:  # name collision
        raise HTTPException(status_code=409, detail=str(e))
    await mongo_pool.evict(connection_id)
    return _mask_base(connection)


@router.post("/connections/{connection_id}/test", dependencies=[Depends(requires("connection:test"))])
async def test_connection(
    connection_id: str,
    store: ConnectionStore = Depends(get_connection_store),
):
    """Lightweight connectivity probe. Returns
    `{ok: bool, elapsed_ms: int, detail: str}`. Does not raise on probe
    failure — the UI shows detail either way."""
    decrypt_context_var.set("connection_test")
    c = await store.get(connection_id)
    if not c:
        raise HTTPException(status_code=404, detail="Connection not found")
    return probe_connection(c)


@router.post("/connections/bulk-delete", dependencies=[Depends(requires("connection:delete"))])
async def bulk_delete_connections(
    body: BulkDeleteRequest,
    c_store: ConnectionStore = Depends(get_connection_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
):
    """Delete many connections in one call. Returns a per-id breakdown so
    partial success (some blocked by references, some already gone) can be
    surfaced by the UI without failing the whole operation."""
    ids = list(dict.fromkeys(body.ids))  # de-dupe, preserve order
    sources = await s_store.list(limit=10_000)
    destinations = await d_store.list(limit=10_000)

    deleted: list[str] = []
    not_found: list[str] = []
    blocked: list[dict] = []
    for cid in ids:
        if not await c_store.get(cid):
            not_found.append(cid)
            continue
        ref_sources = [s.id for s in sources if s.connection_id == cid]
        ref_dests = [d.id for d in destinations if d.connection_id == cid]
        if ref_sources or ref_dests:
            blocked.append({
                "id": cid,
                "referenced_by": {"sources": ref_sources, "destinations": ref_dests},
            })
            continue
        await c_store.delete(cid)
        await mongo_pool.evict(cid)
        deleted.append(cid)
    return {"deleted": deleted, "not_found": not_found, "blocked": blocked}


@router.delete("/connections/{connection_id}", status_code=204, dependencies=[Depends(requires("connection:delete"))])
async def delete_connection(
    connection_id: str,
    c_store: ConnectionStore = Depends(get_connection_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
):
    if not await c_store.get(connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    ref_sources = [
        s.id for s in await s_store.list(limit=10_000)
        if s.connection_id == connection_id
    ]
    ref_dests = [
        d.id for d in await d_store.list(limit=10_000)
        if d.connection_id == connection_id
    ]
    if ref_sources or ref_dests:
        raise HTTPException(
            status_code=409,
            detail={"referenced_by": {"sources": ref_sources, "destinations": ref_dests}},
        )
    await c_store.delete(connection_id)
    await mongo_pool.evict(connection_id)
    return Response(status_code=204)
