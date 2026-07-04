from __future__ import annotations
from fastapi import APIRouter, HTTPException
from dte.models.pipeline import DltSource
from dte.engine.duckdb_engine import DuckDBEngine
from dte.sources.dlt_loader import load_source

router = APIRouter()


@router.post("/schema/infer")
async def infer_schema(source: DltSource):
    engine = DuckDBEngine()
    try:
        table = load_source(source, engine.con)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    fields = [{"name": name, "type": str(dtype)} for name, dtype in table.schema().items()]
    return {"fields": fields}
