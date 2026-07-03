from fastapi import APIRouter, HTTPException

router = APIRouter()


def _get_runs():
    from dte.api.main import _runs
    return _runs


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    _runs = _get_runs()
    if run_id not in _runs:
        raise HTTPException(status_code=404, detail="Run not found")
    return _runs[run_id]
