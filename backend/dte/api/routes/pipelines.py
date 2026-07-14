from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter, HTTPException, Depends, Response
from dte.models.pipeline import Pipeline, Source, Destination
from dte.compiler.ibis_compiler import compile_pipeline
from dte.engine.duckdb_engine import DuckDBEngine
from dte.sources.loader import load_source
from dte.api.deps import (
    get_pipeline_store,
    get_run_store,
    get_source_store,
    get_destination_store,
)
from dte.store.base import PipelineStore, RunStore, SourceStore, DestinationStore

router = APIRouter()


async def _validate_refs(pipeline: Pipeline, s_store: SourceStore, d_store: DestinationStore):
    """Raise 422 if any source id or the destination id doesn't exist."""
    missing_sources = []
    for sid in pipeline.sources:
        if not await s_store.get(sid):
            missing_sources.append(sid)
    missing_dest = None if await d_store.get(pipeline.output_id) else pipeline.output_id
    if missing_sources or missing_dest:
        detail = {}
        if missing_sources:
            detail["missing_sources"] = missing_sources
        if missing_dest:
            detail["missing_destination"] = missing_dest
        raise HTTPException(status_code=422, detail=detail)


@router.post("/pipelines")
async def create_pipeline(
    pipeline: Pipeline,
    store: PipelineStore = Depends(get_pipeline_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
):
    await _validate_refs(pipeline, s_store, d_store)
    await store.save(pipeline.model_dump())
    return {"id": pipeline.id}


@router.get("/pipelines")
async def list_pipelines(limit: int = 50, offset: int = 0, store: PipelineStore = Depends(get_pipeline_store)):
    return await store.list(limit=limit, offset=offset)


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline(pipeline_id: str, store: PipelineStore = Depends(get_pipeline_store)):
    p = await store.get(pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return p


@router.put("/pipelines/{pipeline_id}")
async def update_pipeline(
    pipeline_id: str,
    pipeline: Pipeline,
    store: PipelineStore = Depends(get_pipeline_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
):
    if pipeline.id != pipeline_id:
        raise HTTPException(status_code=400, detail="Pipeline id in path and body must match")
    existing = await store.get(pipeline_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    await _validate_refs(pipeline, s_store, d_store)
    payload = pipeline.model_dump()
    await store.save(payload)
    return payload


@router.delete("/pipelines/{pipeline_id}", status_code=204)
async def delete_pipeline(
    pipeline_id: str,
    p_store: PipelineStore = Depends(get_pipeline_store),
    r_store: RunStore = Depends(get_run_store),
):
    existing = await p_store.get(pipeline_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    await r_store.delete_for_pipeline(pipeline_id)
    await p_store.delete(pipeline_id)
    return Response(status_code=204)


async def _resolve(pipeline: Pipeline, s_store: SourceStore, d_store: DestinationStore):
    """Return (list[Source], Destination). 422 on any missing id."""
    sources: list[Source] = []
    for sid in pipeline.sources:
        raw = await s_store.get(sid)
        if not raw:
            raise HTTPException(status_code=422, detail=f"Source not found: {sid}")
        sources.append(Source(**raw))
    raw_d = await d_store.get(pipeline.output_id)
    if not raw_d:
        raise HTTPException(status_code=422, detail=f"Destination not found: {pipeline.output_id}")
    destination = Destination(**raw_d)
    return sources, destination


@router.get("/pipelines/{pipeline_id}/preview")
async def preview_pipeline(
    pipeline_id: str,
    limit: int = 100,
    store: PipelineStore = Depends(get_pipeline_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
):
    pipeline_dict = await store.get(pipeline_id)
    if not pipeline_dict:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    try:
        pipeline = Pipeline(**pipeline_dict)
        sources, destination = await _resolve(pipeline, s_store, d_store)
        engine = DuckDBEngine()
        tables = {s.id: load_source(s, engine.con) for s in sources}
        compiled = compile_pipeline(pipeline, tables, output=destination.config)
        df = compiled.limit(limit).execute()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    rows = json.loads(df.to_json(orient="records", date_format="iso"))
    return {"rows": rows, "count": len(rows)}


@router.post("/pipelines/{pipeline_id}/trigger")
async def trigger_pipeline(
    pipeline_id: str,
    p_store: PipelineStore = Depends(get_pipeline_store),
    r_store: RunStore = Depends(get_run_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
):
    p = await p_store.get(pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    pipeline = Pipeline(**p)
    # Fail fast on missing refs before creating a run.
    await _resolve(pipeline, s_store, d_store)
    run_id = await r_store.create(pipeline_id)
    asyncio.create_task(_execute_pipeline(pipeline_id, run_id, p_store, r_store, s_store, d_store))
    return {"run_id": run_id}


async def _execute_pipeline(
    pipeline_id: str,
    run_id: str,
    p_store: PipelineStore,
    r_store: RunStore,
    s_store: SourceStore,
    d_store: DestinationStore,
):
    await r_store.update(run_id, status="running")
    try:
        pipeline_dict = await p_store.get(pipeline_id)
        pipeline = Pipeline(**pipeline_dict)
        sources: list[Source] = []
        for sid in pipeline.sources:
            raw = await s_store.get(sid)
            if not raw:
                raise ValueError(f"Source not found: {sid}")
            sources.append(Source(**raw))
        raw_d = await d_store.get(pipeline.output_id)
        if not raw_d:
            raise ValueError(f"Destination not found: {pipeline.output_id}")
        destination = Destination(**raw_d)

        engine = DuckDBEngine()
        tables = {s.id: load_source(s, engine.con) for s in sources}
        compiled = compile_pipeline(pipeline, tables, output=destination.config)
        result = engine.execute(compiled, destination.config)
        await r_store.update(
            run_id,
            status="completed",
            rows_written=result["rows_written"],
            location=result["location"],
        )
    except Exception as e:
        await r_store.update(
            run_id,
            status="failed",
            error=str(e),
        )
