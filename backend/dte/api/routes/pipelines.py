from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter, HTTPException, Depends, Response
from dte.models.pipeline import Pipeline, PipelineBase, Source, Destination
from dte.compiler.ibis_compiler import compile_pipeline
from dte.engine.duckdb_engine import DuckDBEngine
from dte.sources.loader import load_source
from dte.api.deps import (
    get_pipeline_store,
    get_run_store,
    get_source_store,
    get_destination_store,
    get_connection_store,
)
from dte.store.base import (
    PipelineStore, RunStore, SourceStore, DestinationStore, ConnectionStore,
)

router = APIRouter()


async def _validate_pipeline_refs(
    pipeline: PipelineBase,
    s_store: SourceStore,
    d_store: DestinationStore,
):
    """Raise 422 if any source id or the destination id doesn't exist."""
    missing_sources = []
    for sid in pipeline.sources:
        if not await s_store.get(sid):
            missing_sources.append(sid)
    missing_dest = None if await d_store.get(pipeline.output_id) else pipeline.output_id
    if missing_sources or missing_dest:
        detail: dict = {}
        if missing_sources:
            detail["missing_sources"] = missing_sources
        if missing_dest:
            detail["missing_destination"] = missing_dest
        raise HTTPException(status_code=422, detail=detail)


@router.post("/pipelines")
async def create_pipeline(
    pipeline: PipelineBase,
    store: PipelineStore = Depends(get_pipeline_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
):
    await _validate_pipeline_refs(pipeline, s_store, d_store)
    await store.save(Pipeline(**pipeline.model_dump()))
    return {"id": pipeline.id}


@router.get("/pipelines")
async def list_pipelines(limit: int = 50, offset: int = 0, store: PipelineStore = Depends(get_pipeline_store)) -> list[Pipeline]:
    return await store.list(limit=limit, offset=offset)


@router.get("/pipelines/{pipeline_id}")
async def get_pipeline(pipeline_id: str, store: PipelineStore = Depends(get_pipeline_store)) -> Pipeline:
    p = await store.get(pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return p


@router.put("/pipelines/{pipeline_id}")
async def update_pipeline(
    pipeline_id: str,
    pipeline: PipelineBase,
    store: PipelineStore = Depends(get_pipeline_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
) -> Pipeline:
    if pipeline.id != pipeline_id:
        raise HTTPException(status_code=400, detail="Pipeline id in path and body must match")
    existing = await store.get(pipeline_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    await _validate_pipeline_refs(pipeline, s_store, d_store)
    row = Pipeline(**pipeline.model_dump())
    await store.save(row)
    return row


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


async def _resolve(
    pipeline: Pipeline,
    s_store: SourceStore,
    d_store: DestinationStore,
    c_store: ConnectionStore,
) -> tuple[list[tuple[Source, dict]], tuple[Destination, dict]]:
    """Resolve pipeline id refs to (Source, credentials) tuples and
    (Destination, credentials). Missing anything → 422 naming what's gone."""
    sources: list[tuple[Source, dict]] = []
    for sid in pipeline.sources:
        source = await s_store.get(sid)
        if not source:
            raise HTTPException(status_code=422, detail=f"Source not found: {sid}")
        conn = await c_store.get(source.connection_id)
        if not conn:
            raise HTTPException(
                status_code=422,
                detail=f"Source '{sid}' references missing connection '{source.connection_id}'",
            )
        sources.append((source, conn.credentials))

    destination = await d_store.get(pipeline.output_id)
    if not destination:
        raise HTTPException(status_code=422, detail=f"Destination not found: {pipeline.output_id}")
    dest_conn = await c_store.get(destination.connection_id)
    if not dest_conn:
        raise HTTPException(
            status_code=422,
            detail=f"Destination '{destination.id}' references missing connection '{destination.connection_id}'",
        )
    return sources, (destination, dest_conn.credentials)


@router.get("/pipelines/{pipeline_id}/preview")
async def preview_pipeline(
    pipeline_id: str,
    limit: int = 100,
    store: PipelineStore = Depends(get_pipeline_store),
    s_store: SourceStore = Depends(get_source_store),
    d_store: DestinationStore = Depends(get_destination_store),
    c_store: ConnectionStore = Depends(get_connection_store),
):
    pipeline = await store.get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    try:
        sources, (destination, _) = await _resolve(pipeline, s_store, d_store, c_store)
        engine = DuckDBEngine()
        tables = {s.id: load_source(s, engine.con, creds) for s, creds in sources}
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
    c_store: ConnectionStore = Depends(get_connection_store),
):
    pipeline = await p_store.get(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    # Fail fast on missing refs before creating a run.
    await _resolve(pipeline, s_store, d_store, c_store)
    run_id = await r_store.create(pipeline_id)
    asyncio.create_task(
        _execute_pipeline(pipeline_id, run_id, p_store, r_store, s_store, d_store, c_store)
    )
    return {"run_id": run_id}


async def _execute_pipeline(
    pipeline_id: str,
    run_id: str,
    p_store: PipelineStore,
    r_store: RunStore,
    s_store: SourceStore,
    d_store: DestinationStore,
    c_store: ConnectionStore,
):
    await r_store.update(run_id, status="running")
    try:
        pipeline = await p_store.get(pipeline_id)
        sources, (destination, dest_creds) = await _resolve(pipeline, s_store, d_store, c_store)

        engine = DuckDBEngine()
        tables = {s.id: load_source(s, engine.con, creds) for s, creds in sources}
        compiled = compile_pipeline(pipeline, tables, output=destination.config)
        result = engine.execute(compiled, destination.config, credentials=dest_creds)
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
