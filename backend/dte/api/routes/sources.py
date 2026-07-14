from __future__ import annotations
from fastapi import APIRouter, HTTPException, Depends, Response
import ibis.expr.datatypes as dt

from dte.models.pipeline import Source, Pipeline
from dte.engine.duckdb_engine import DuckDBEngine
from dte.sources.loader import load_source
from dte.api.deps import get_source_store, get_pipeline_store
from dte.api.routes.schema import SchemaFieldNode, InferSchemaResponse, _walk
from dte.store.base import SourceStore, PipelineStore

router = APIRouter()


@router.post("/sources", status_code=201)
async def create_source(source: Source, store: SourceStore = Depends(get_source_store)):
    if await store.get(source.id):
        raise HTTPException(status_code=409, detail=f"Source '{source.id}' already exists")
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
):
    if source.id != source_id:
        raise HTTPException(status_code=400, detail="Source id in path and body must match")
    if not await store.get(source_id):
        raise HTTPException(status_code=404, detail="Source not found")
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
        p["id"] for p in await p_store.list(limit=10_000)
        if source_id in (p.get("sources") or [])
    ]
    if referenced_by:
        raise HTTPException(status_code=409, detail={"referenced_by": referenced_by})
    await s_store.delete(source_id)
    return Response(status_code=204)


@router.get("/sources/{source_id}/schema", response_model=InferSchemaResponse)
async def source_schema(source_id: str, store: SourceStore = Depends(get_source_store)):
    raw = await store.get(source_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Source not found")
    source = Source(**raw)
    engine = DuckDBEngine()
    try:
        table = load_source(source, engine.con)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
    fields = [_walk(name, dtype) for name, dtype in table.schema().items()]
    return InferSchemaResponse(fields=fields)
