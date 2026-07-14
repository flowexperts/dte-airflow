from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends, Response

from dte.models.pipeline import Connection
from dte.api.deps import (
    get_connection_store,
    get_source_store,
    get_destination_store,
)
from dte.sources.connection_test import probe_connection
from dte.store.base import ConnectionStore, SourceStore, DestinationStore

router = APIRouter()


def _mask(c: dict) -> dict:
    creds = c.get("credentials") or {}
    return {**c, "credentials": {k: "***" for k in creds}}


@router.post("/connections", status_code=201)
async def create_connection(
    connection: Connection,
    store: ConnectionStore = Depends(get_connection_store),
):
    if await store.get(connection.id):
        raise HTTPException(status_code=409, detail=f"Connection '{connection.id}' already exists")
    await store.save(connection.model_dump())
    return _mask(connection.model_dump())


@router.get("/connections")
async def list_connections(
    limit: int = 50,
    offset: int = 0,
    store: ConnectionStore = Depends(get_connection_store),
):
    return await store.list(limit=limit, offset=offset)


@router.get("/connections/{connection_id}")
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
        return c
    return _mask(c)


@router.put("/connections/{connection_id}")
async def update_connection(
    connection_id: str,
    connection: Connection,
    store: ConnectionStore = Depends(get_connection_store),
):
    if connection.id != connection_id:
        raise HTTPException(status_code=400, detail="Connection id in path and body must match")
    existing = await store.get(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Connection not found")
    payload = connection.model_dump()
    # If credentials omitted (empty dict) on PUT, keep the existing set.
    if not payload.get("credentials"):
        payload["credentials"] = existing.get("credentials", {})
    await store.save(payload)
    return _mask(payload)


@router.post("/connections/{connection_id}/test")
async def test_connection(
    connection_id: str,
    store: ConnectionStore = Depends(get_connection_store),
):
    """Lightweight connectivity probe. Returns
    `{ok: bool, elapsed_ms: int, detail: str}`. Does not raise on probe
    failure — the UI shows detail either way."""
    raw = await store.get(connection_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Connection not found")
    return probe_connection(Connection(**raw))


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: str,
    c_store: ConnectionStore = Depends(get_connection_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
):
    if not await c_store.get(connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    ref_sources = [
        s["id"] for s in await s_store.list(limit=10_000)
        if s.get("connection_id") == connection_id
    ]
    ref_dests = [
        d["id"] for d in await d_store.list(limit=10_000)
        if d.get("connection_id") == connection_id
    ]
    if ref_sources or ref_dests:
        raise HTTPException(
            status_code=409,
            detail={"referenced_by": {"sources": ref_sources, "destinations": ref_dests}},
        )
    await c_store.delete(connection_id)
    return Response(status_code=204)
