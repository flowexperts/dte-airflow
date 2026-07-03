from __future__ import annotations
import asyncio
import uuid
from fastapi import APIRouter, HTTPException
from dte.models.pipeline import Pipeline
from dte.compiler.ibis_compiler import compile_pipeline
from dte.engine.duckdb_engine import DuckDBEngine
from dte.sources.dlt_loader import load_source

router = APIRouter()


def _get_stores():
    from dte.api.main import _pipelines, _runs
    return _pipelines, _runs


@router.post("/pipelines")
def create_pipeline(pipeline: Pipeline):
    _pipelines, _ = _get_stores()
    _pipelines[pipeline.id] = pipeline.model_dump()
    return {"id": pipeline.id}


@router.get("/pipelines/{pipeline_id}")
def get_pipeline(pipeline_id: str):
    _pipelines, _ = _get_stores()
    if pipeline_id not in _pipelines:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return _pipelines[pipeline_id]


@router.post("/pipelines/{pipeline_id}/trigger")
async def trigger_pipeline(pipeline_id: str):
    _pipelines, _runs = _get_stores()
    if pipeline_id not in _pipelines:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    run_id = str(uuid.uuid4())
    _runs[run_id] = {"status": "pending", "error": None, "rows_written": None, "pipeline_id": pipeline_id}

    asyncio.create_task(_execute_pipeline(pipeline_id, run_id))
    return {"run_id": run_id}


async def _execute_pipeline(pipeline_id: str, run_id: str):
    _pipelines, _runs = _get_stores()
    _runs[run_id]["status"] = "running"
    try:
        pipeline = Pipeline(**_pipelines[pipeline_id])
        engine = DuckDBEngine()
        tables = {}
        for source in pipeline.sources:
            tables[source.id] = load_source(source, engine.con)

        compiled = compile_pipeline(pipeline, tables)
        rows = engine.execute_to_json(compiled, pipeline.output.path)
        _runs[run_id]["status"] = "completed"
        _runs[run_id]["rows_written"] = rows
    except Exception as e:
        _runs[run_id]["status"] = "failed"
        _runs[run_id]["error"] = str(e)
