from fastapi import APIRouter, HTTPException, Depends
from dte.api.deps import get_run_store
from dte.store.base import RunStore

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
