import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dte.api.routes.pipelines import router as pipelines_router
from dte.api.routes.runs import router as runs_router
from dte.api.routes.schema import router as schema_router

app = FastAPI(title="DTE API")

_origins = os.environ.get("DTE_CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pipelines_router, prefix="/api")
app.include_router(runs_router, prefix="/api")
app.include_router(schema_router, prefix="/api")
