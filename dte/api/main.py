from fastapi import FastAPI
from dte.api.routes.pipelines import router as pipelines_router
from dte.api.routes.runs import router as runs_router

app = FastAPI(title="DTE API")

_pipelines: dict[str, dict] = {}
_runs: dict[str, dict] = {}

app.include_router(pipelines_router, prefix="/api")
app.include_router(runs_router, prefix="/api")
