from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from dte.api.deps import (
    get_connection_store,
    get_pipeline_store,
    get_source_store,
)

BULK_DELETE_LIMIT = 200


class BulkDeleteRequest(BaseModel):
    ids: list[str] = Field(..., min_length=1, max_length=BULK_DELETE_LIMIT)
from dte.api.interactive import run_interactive
from dte.api.routes.schema import InferSchemaResponse, source_fields
from dte.models.pipeline import (
    SOURCE_CONNECTION_COMPAT,
    Source,
    SourceBase,
    coerce_source_refs,
)
from dte.security.permissions import requires
from dte.store.base import ConnectionStore, PipelineStore, SourceStore

router = APIRouter()


async def _validate_connection(source: SourceBase | Source, c_store: ConnectionStore):
    """Fetch the linked connection and verify its type is compatible with
    `source.source_type`. Raises 422 otherwise. Returns the Connection."""
    conn = await c_store.get(source.connection_id)
    if not conn:
        raise HTTPException(
            status_code=422,
            detail=f"Connection '{source.connection_id}' does not exist",
        )
    allowed = SOURCE_CONNECTION_COMPAT.get(source.source_type, set())
    if conn.connection_type not in allowed:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Source type '{source.source_type}' is not compatible with "
                f"connection type '{conn.connection_type}' (allowed: {sorted(allowed)})"
            ),
        )
    return conn


@router.post("/sources", status_code=201, dependencies=[Depends(requires("source:write"))])
async def create_source(
    source: SourceBase,
    store: SourceStore = Depends(get_source_store),
    c_store: ConnectionStore = Depends(get_connection_store),
):
    if await store.get(source.id):
        raise HTTPException(status_code=409, detail=f"Source '{source.id}' already exists")
    await _validate_connection(source, c_store)
    try:
        await store.save(source)
    except ValueError as e:  # name collision
        raise HTTPException(status_code=409, detail=str(e))
    return source.model_dump()


@router.get("/sources", dependencies=[Depends(requires("source:read"))])
async def list_sources(limit: int = 50, offset: int = 0, store: SourceStore = Depends(get_source_store)):
    sources = await store.list(limit=limit, offset=offset)
    return [s.model_dump() for s in sources]


@router.get("/sources/{source_id}", dependencies=[Depends(requires("source:read"))])
async def get_source(source_id: str, store: SourceStore = Depends(get_source_store)):
    s = await store.get(source_id)
    if not s:
        raise HTTPException(status_code=404, detail="Source not found")
    return s.model_dump()


@router.put("/sources/{source_id}", dependencies=[Depends(requires("source:write"))])
async def update_source(
    source_id: str,
    source: SourceBase,
    store: SourceStore = Depends(get_source_store),
    c_store: ConnectionStore = Depends(get_connection_store),
):
    if source.id != source_id:
        raise HTTPException(status_code=400, detail="Source id in path and body must match")
    if not await store.get(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    await _validate_connection(source, c_store)
    try:
        await store.save(source)
    except ValueError as e:  # name collision
        raise HTTPException(status_code=409, detail=str(e))
    return source.model_dump()


@router.post("/sources/bulk-delete", dependencies=[Depends(requires("source:delete"))])
async def bulk_delete_sources(
    body: BulkDeleteRequest,
    s_store: SourceStore = Depends(get_source_store),
    p_store: PipelineStore = Depends(get_pipeline_store),
):
    ids = list(dict.fromkeys(body.ids))
    pipelines = await p_store.list(limit=10_000)

    deleted: list[str] = []
    not_found: list[str] = []
    blocked: list[dict] = []
    for sid in ids:
        if not await s_store.get(sid):
            not_found.append(sid)
            continue
        referenced_by = [
            p.id for p in pipelines
            if any(r.source_id == sid for r in coerce_source_refs(p.sources or []))
        ]
        if referenced_by:
            blocked.append({"id": sid, "referenced_by": referenced_by})
            continue
        await s_store.delete(sid)
        deleted.append(sid)
    return {"deleted": deleted, "not_found": not_found, "blocked": blocked}


@router.delete("/sources/{source_id}", status_code=204, dependencies=[Depends(requires("source:delete"))])
async def delete_source(
    source_id: str,
    s_store: SourceStore = Depends(get_source_store),
    p_store: PipelineStore = Depends(get_pipeline_store),
):
    if not await s_store.get(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
    referenced_by = [
        p.id for p in await p_store.list(limit=10_000)
        if any(r.source_id == source_id for r in coerce_source_refs(p.sources or []))
    ]
    if referenced_by:
        raise HTTPException(status_code=409, detail={"referenced_by": referenced_by})
    await s_store.delete(source_id)
    return Response(status_code=204)


@router.get("/sources/{source_id}/schema", response_model=InferSchemaResponse, dependencies=[Depends(requires("source:read"))])
async def source_schema(
    source_id: str,
    table: str | None = None,
    store: SourceStore = Depends(get_source_store),
    c_store: ConnectionStore = Depends(get_connection_store),
):
    """`table` — required for `sql_database` sources (they no longer carry
    a table in their own config; which table is read is a
    per-pipeline-per-use decision). Ignored for every other kind."""
    source = await store.get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    # Validate that required fields are present (legacy rows may be missing
    # connection_id if migrated incompletely).
    if not source.connection_id:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Source '{source_id}' is missing required field(s): connection_id. "
                f"This looks like a legacy row — open it in the source editor and re-save."
            ),
        )
    conn = await c_store.get(source.connection_id)
    if not conn:
        raise HTTPException(
            status_code=422,
            detail=f"Source '{source_id}' references missing connection '{source.connection_id}'",
        )
    return await run_interactive(source_fields, source, conn, table)


@router.get("/sources/{source_id}/tables", dependencies=[Depends(requires("source:read"))])
async def source_tables(
    source_id: str,
    store: SourceStore = Depends(get_source_store),
    c_store: ConnectionStore = Depends(get_connection_store),
):
    """Table names visible through a `sql_database` source's connection,
    respecting the source's configured `schema` if any. 422 (not 500) for
    non-`sql_database` sources or a real driver failure."""
    source = await store.get(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.source_type != "sql_database":
        raise HTTPException(
            status_code=422,
            detail=f"Source '{source_id}' is a {source.source_type!r} source — "
            "table listing only applies to sql_database sources",
        )
    conn = await c_store.get(source.connection_id)
    if not conn:
        raise HTTPException(
            status_code=422,
            detail=f"Source '{source_id}' references missing connection '{source.connection_id}'",
        )
    from dte.sources.loader import list_tables as _list_tables
    try:
        tables = await run_interactive(
            _list_tables, conn, conn.credentials, schema=source.config.get("schema"),
        )
    except NotImplementedError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"{type(e).__name__}: {e}")
    return {"tables": tables}
