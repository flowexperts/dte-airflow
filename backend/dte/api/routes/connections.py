from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends, Response
from dte.security.permissions import requires

from dte.models.pipeline import Connection, ConnectionBase
from dte.api.deps import (
    get_connection_store,
    get_source_store,
    get_destination_store,
)
from dte.sources.connection_test import probe_connection
from dte.store.base import ConnectionStore, SourceStore, DestinationStore

router = APIRouter()


def _mask(c: Connection) -> dict:
    """Return a plain dict with credentials values replaced by '***'."""
    return {
        "id": c.id,
        "connection_type": c.connection_type,
        "credentials": {k: "***" for k in c.credentials},
    }


@router.post("/connections", status_code=201, dependencies=[Depends(requires("connection:write"))])
async def create_connection(
    connection: ConnectionBase,
    store: ConnectionStore = Depends(get_connection_store),
):
    if await store.get(connection.id):
        raise HTTPException(status_code=409, detail=f"Connection '{connection.id}' already exists")
    await store.save(connection)
    return _mask_base(connection)


def _mask_base(connection: ConnectionBase) -> dict:
    """Mask credentials from a ConnectionBase (used for POST/PUT responses)."""
    creds = connection.credentials or {}
    return {
        "id": connection.id,
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
    c = await store.get(connection_id)
    if not c:
        raise HTTPException(status_code=404, detail="Connection not found")
    if reveal:
        # Reveal path is a deliberate escape hatch (e.g., the UI edit form
        # pre-populating fields). Callers should treat this as sensitive.
        return {
            "id": c.id,
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
    if connection.id != connection_id:
        raise HTTPException(status_code=400, detail="Connection id in path and body must match")
    existing = await store.get(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Connection not found")
    # If credentials omitted (empty dict) on PUT, keep the existing set.
    if not connection.credentials:
        existing_creds = existing.credentials
        connection = ConnectionBase(
            id=connection.id,
            connection_type=connection.connection_type,
            credentials=existing_creds,
        )
    await store.save(connection)
    return _mask_base(connection)


@router.post("/connections/{connection_id}/test", dependencies=[Depends(requires("connection:test"))])
async def test_connection(
    connection_id: str,
    store: ConnectionStore = Depends(get_connection_store),
):
    """Lightweight connectivity probe. Returns
    `{ok: bool, elapsed_ms: int, detail: str}`. Does not raise on probe
    failure — the UI shows detail either way."""
    c = await store.get(connection_id)
    if not c:
        raise HTTPException(status_code=404, detail="Connection not found")
    return probe_connection(c)


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
    return Response(status_code=204)
