"""Read-only connection routes. Connections are Airflow Connections (plan 065):
create, edit and delete them in the Airflow UI (Admin -> Connections)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from dte.api.deps import get_connection_store
from dte.logging import decrypt_context_var
from dte.models.pipeline import Connection
from dte.security.permissions import requires
from dte.sources.connection_test import probe_connection
from dte.store.base import ConnectionStore

router = APIRouter()


def _mask(c: Connection) -> dict:
    return {
        "id": c.id,
        "name": c.name or c.id,
        "connection_type": c.connection_type,
        "credentials": {k: "***" for k in c.credentials},
    }


@router.get("/capabilities", dependencies=[Depends(requires("connection:read"))])
async def capabilities():
    """What this deployment can read and write, from the installed Airflow
    providers (plan 074). Unavailable connection kinds name what to install."""
    from dte.airflow import connections as ac
    from dte.models.pipeline import DESTINATION_CONNECTION_COMPAT, SOURCE_CONNECTION_COMPAT

    have = ac.available_kinds()
    return {
        "connection_kinds": {k: {"available": k in have, "install": None if k in have else hint}
                             for k, (_, hint) in ac.KINDS.items()},
        "source_kinds": {k: bool(v & have) for k, v in SOURCE_CONNECTION_COMPAT.items()},
        "destination_types": {k: bool(v & have) for k, v in DESTINATION_CONNECTION_COMPAT.items()},
    }


@router.get("/connections", dependencies=[Depends(requires("connection:read"))])
async def list_connections(
    limit: int = 50,
    offset: int = 0,
    store: ConnectionStore = Depends(get_connection_store),
):
    return [_mask(c) for c in await store.list(limit=limit, offset=offset)]


@router.get("/connections/{connection_id}", dependencies=[Depends(requires("connection:read"))])
async def get_connection(connection_id: str, store: ConnectionStore = Depends(get_connection_store)):
    c = await store.get(connection_id)
    if not c:
        raise HTTPException(status_code=404, detail="Connection not found")
    return _mask(c)


@router.post("/connections/{connection_id}/test", dependencies=[Depends(requires("connection:test"))])
async def test_connection(connection_id: str, store: ConnectionStore = Depends(get_connection_store)):
    """Connectivity probe: `{ok, elapsed_ms, detail}`; never raises on probe failure."""
    decrypt_context_var.set("connection_test")
    c = await store.get(connection_id)
    if not c:
        raise HTTPException(status_code=404, detail="Connection not found")
    return probe_connection(c)


@router.get("/connections/{connection_id}/schemas", dependencies=[Depends(requires("connection:read"))])
async def list_connection_schemas(connection_id: str, store: ConnectionStore = Depends(get_connection_store)):
    """Schema names visible through a connection's native ibis backend; 422
    for types with no native backend or on a driver failure."""
    decrypt_context_var.set("connection_schemas")
    c = await store.get(connection_id)
    if not c:
        raise HTTPException(status_code=404, detail="Connection not found")
    from dte.sources.loader import list_schemas
    try:
        return {"schemas": list_schemas(c, c.credentials)}
    except NotImplementedError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"{type(e).__name__}: {e}")
