import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dte.api.routes.connections import router as connections_router
from dte.api.routes.destinations import router as destinations_router
from dte.api.routes.pipelines import router as pipelines_router
from dte.api.routes.runs import router as runs_router
from dte.api.routes.schema import router as schema_router
from dte.api.routes.sources import router as sources_router

_DEFAULT_ORIGINS = "http://localhost:3000,http://localhost:5173"

app = FastAPI(title="DTE API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.environ.get("DTE_CORS_ORIGINS", _DEFAULT_ORIGINS).split(",")
        if o.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pipelines_router, prefix="/api")
app.include_router(runs_router, prefix="/api")
app.include_router(schema_router, prefix="/api")
app.include_router(sources_router, prefix="/api")
app.include_router(destinations_router, prefix="/api")
app.include_router(connections_router, prefix="/api")
