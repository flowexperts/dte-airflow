from __future__ import annotations
import asyncio
import json
from fastapi import APIRouter, HTTPException, Depends, Response
from dte.models.pipeline import Pipeline
from dte.compiler.ibis_compiler import compile_pipeline
from dte.engine.duckdb_engine import DuckDBEngine
from dte.sources.dlt_loader import load_source
from dte.api.deps import get_pipeline_store, get_run_store
from dte.store.base import PipelineStore, RunStore

router = APIRouter()


@router.post("/pipelines")
async def create_pipeline(pipeline: Pipeline, store: PipelineStore = Depends(get_pipeline_store)):
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
):
    if pipeline.id != pipeline_id:
        raise HTTPException(status_code=400, detail="Pipeline id in path and body must match")
    existing = await store.get(pipeline_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Pipeline not found")
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


@router.get("/pipelines/{pipeline_id}/preview")
async def preview_pipeline(
    pipeline_id: str,
    limit: int = 100,
    store: PipelineStore = Depends(get_pipeline_store),
):
    pipeline_dict = await store.get(pipeline_id)
    if not pipeline_dict:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    try:
        pipeline = Pipeline(**pipeline_dict)
        engine = DuckDBEngine()
        tables = {s.id: load_source(s, engine.con) for s in pipeline.sources}
        compiled = compile_pipeline(pipeline, tables)
        df = compiled.limit(limit).execute()
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    rows = json.loads(df.to_json(orient="records", date_format="iso"))
    return {"rows": rows, "count": len(rows)}


@router.post("/pipelines/{pipeline_id}/trigger")
async def trigger_pipeline(
    pipeline_id: str,
    p_store: PipelineStore = Depends(get_pipeline_store),
    r_store: RunStore = Depends(get_run_store),
):
    p = await p_store.get(pipeline_id)
    if not p:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    run_id = await r_store.create(pipeline_id)
    asyncio.create_task(_execute_pipeline(pipeline_id, run_id, p_store, r_store))
    return {"run_id": run_id}


async def _execute_pipeline(pipeline_id: str, run_id: str, p_store: PipelineStore, r_store: RunStore):
    await r_store.update(run_id, status="running")
    try:
        pipeline_dict = await p_store.get(pipeline_id)
        pipeline = Pipeline(**pipeline_dict)
        engine = DuckDBEngine()
        tables = {}
        for source in pipeline.sources:
            tables[source.id] = load_source(source, engine.con)

        compiled = compile_pipeline(pipeline, tables)
        rows = engine.execute_to_json(compiled, pipeline.output.path)
        await r_store.update(run_id, status="completed", rows_written=rows)
    except Exception as e:
        await r_store.update(run_id, status="failed", error=str(e))
