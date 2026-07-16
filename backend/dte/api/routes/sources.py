from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends, Response
from pydantic import ValidationError

from dte.models.pipeline import Source, SOURCE_CONNECTION_COMPAT
from dte.engine.duckdb_engine import DuckDBEngine
from dte.sources.loader import load_source
from dte.api.deps import (
    get_source_store, get_pipeline_store, get_connection_store,
)
from dte.api.routes.schema import InferSchemaResponse, _walk
from dte.store.base import SourceStore, PipelineStore, ConnectionStore

router = APIRouter()


async def _validate_connection(source: Source, c_store: ConnectionStore) -> dict:
    """Fetch the linked connection and verify its type is compatible with
    `source.source_type`. Raises 422 otherwise."""
    conn = await c_store.get(source.connection_id)
    if not conn:
        raise HTTPException(
            status_code=422,
            detail=f"Connection '{source.connection_id}' does not exist",
        )
    allowed = SOURCE_CONNECTION_COMPAT.get(source.source_type, set())
    if conn["connection_type"] not in allowed:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Source type '{source.source_type}' is not compatible with "
                f"connection type '{conn['connection_type']}' (allowed: {sorted(allowed)})"
            ),
        )
    return conn


@router.post("/sources", status_code=201)
async def create_source(
    source: Source,
    store: SourceStore = Depends(get_source_store),
    c_store: ConnectionStore = Depends(get_connection_store),
):
    if await store.get(source.id):
        raise HTTPException(status_code=409, detail=f"Source '{source.id}' already exists")
    await _validate_connection(source, c_store)
    await store.save(source.model_dump())
    return source.model_dump()


@router.get("/sources")
async def list_sources(limit: int = 50, offset: int = 0, store: SourceStore = Depends(get_source_store)):
    return await store.list(limit=limit, offset=offset)


@router.get("/sources/{source_id}")
async def get_source(source_id: str, store: SourceStore = Depends(get_source_store)):
    s = await store.get(source_id)
    if not s:
        raise HTTPException(status_code=404, detail="Source not found")
    return s


@router.put("/sources/{source_id}")
async def update_source(
    source_id: str,
    source: Source,
    store: SourceStore = Depends(get_source_store),
    c_store: ConnectionStore = Depends(get_connection_store),
):
    if source.id != source_id:
        raise HTTPException(status_code=400, detail="Source id in path and body must match")
    if not await store.get(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    await _validate_connection(source, c_store)
    payload = source.model_dump()
    await store.save(payload)
    return payload


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(
    source_id: str,
    s_store: SourceStore = Depends(get_source_store),
    p_store: PipelineStore = Depends(get_pipeline_store),
):
    if not await s_store.get(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    referenced_by = [
        p.id for p in await p_store.list(limit=10_000)
        if source_id in (p.sources or [])
    ]
    if referenced_by:
        raise HTTPException(status_code=409, detail={"referenced_by": referenced_by})
    await s_store.delete(source_id)
    return Response(status_code=204)


@router.get("/sources/{source_id}/schema", response_model=InferSchemaResponse)
async def source_schema(
    source_id: str,
    store: SourceStore = Depends(get_source_store),
    c_store: ConnectionStore = Depends(get_connection_store),
):
    raw = await store.get(source_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        source = Source(**raw)
    except ValidationError as e:
        missing = [".".join(str(p) for p in err["loc"]) for err in e.errors() if err["type"] == "missing"]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Source '{source_id}' is missing required field(s): {', '.join(missing)}. "
                    f"This looks like a legacy row — open it in the source editor and re-save, "
                    f"or run backend/scripts/migrate_extract_connections.py."
                ),
            )
        raise HTTPException(status_code=422, detail=str(e))
    conn = await c_store.get(source.connection_id)
    if not conn:
        raise HTTPException(
            status_code=422,
            detail=f"Source '{source_id}' references missing connection '{source.connection_id}'",
        )
    engine = DuckDBEngine()
    try:
        table = load_source(source, engine.con, conn.get("credentials") or {})
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    fields = [_walk(name, dtype) for name, dtype in table.schema().items()]
    return InferSchemaResponse(fields=fields)
