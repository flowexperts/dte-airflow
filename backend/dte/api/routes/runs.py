from __future__ import annotations
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from dte.api.deps import get_run_store, get_pipeline_store, get_destination_store
from dte.store.base import RunStore, PipelineStore, DestinationStore
from dte.models.pipeline import Pipeline, Destination

router = APIRouter()


@router.get("/runs/{run_id}")
async def get_run(run_id: str, store: RunStore = Depends(get_run_store)):
    run = await store.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/pipelines/{pipeline_id}/runs")
async def list_runs_for_pipeline(
    pipeline_id: str,
    limit: int = 50,
    store: RunStore = Depends(get_run_store),
):
    return await store.list_for_pipeline(pipeline_id, limit=limit)


@router.get("/runs/{run_id}/output")
async def get_run_output(
    run_id: str,
    limit: int = 5,
    r_store: RunStore = Depends(get_run_store),
    p_store: PipelineStore = Depends(get_pipeline_store),
    d_store: DestinationStore = Depends(get_destination_store),
):
    run = await r_store.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Run has not completed")
    location = run.get("location")
    if not location:
        raise HTTPException(status_code=400, detail="Run has no recorded output location")

    pipeline = await p_store.get(run["pipeline_id"])
    if not pipeline:
        raise HTTPException(status_code=404, detail="Parent pipeline not found")
    raw_dest = await d_store.get(pipeline.output_id)
    if not raw_dest:
        raise HTTPException(status_code=404, detail="Destination not found")
    output_type = Destination(**raw_dest).config.type

    try:
        if output_type == "json_file":
            data = json.loads(Path(location).read_text())
            rows = data[:limit] if isinstance(data, list) else [data]
        elif output_type == "csv_file":
            import pandas as pd
            df = pd.read_csv(location, nrows=limit)
            rows = json.loads(df.to_json(orient="records", date_format="iso"))
        elif output_type == "excel_file":
            # DuckDB's excel extension for read too — keeps openpyxl out
            # of the dep tree and matches how the writer produced it.
            import ibis
            con = ibis.duckdb.connect()
            con.raw_sql("INSTALL excel")
            con.raw_sql("LOAD excel")
            df = con.sql(
                f"SELECT * FROM read_xlsx('{location.replace(chr(39), chr(39)*2)}') "
                f"LIMIT {int(limit)}"
            ).execute()
            rows = json.loads(df.to_json(orient="records", date_format="iso"))
        else:
            raise HTTPException(
                status_code=400,
                detail=f"preview not supported for {output_type} outputs",
            )
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Output file missing at {location}")
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"rows": rows, "count": len(rows)}
