"""The DTE API, mounted by the Airflow plugin at `/dte` (plan 065).

Routes live under `/dte/api/*`; the static UI export is served at `/dte/ui`.
Auth is Airflow's (see `dte.airflow.auth`); every route already carries a
`requires(...)` permission dependency.
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from dte import metrics  # noqa: F401 — import-side Prometheus counter/histogram registration
from dte.airflow.trigger import capture_auth
from dte.api.error_handlers import register as register_error_handlers
from dte.api.middleware import RequestContextMiddleware
from dte.api.routes.artifacts import router as artifacts_router
from dte.api.routes.connections import router as connections_router
from dte.api.routes.dashboards import router as dashboards_router
from dte.api.routes.destinations import router as destinations_router
from dte.api.routes.evals import router as evals_router
from dte.api.routes.health import router as health_router
from dte.api.routes.lookup_tables import router as lookup_tables_router
from dte.api.routes.me import router as me_router
from dte.api.routes.notifications import router as notifications_router
from dte.api.routes.pipelines import router as pipelines_router
from dte.api.routes.providers import router as providers_router
from dte.api.routes.runs import router as runs_router
from dte.api.routes.schedules import router as schedules_router
from dte.api.routes.schema import router as schema_router
from dte.api.routes.sources import router as sources_router
from dte.logging import configure_logging
from dte.sources.pools import mongo as mongo_pool

configure_logging()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    yield
    await mongo_pool.close_all()  # close pooled Mongo clients


app = FastAPI(title="DTE API", lifespan=_lifespan)
app.add_middleware(RequestContextMiddleware)
register_error_handlers(app)

app.include_router(health_router)
# capture_auth stashes the caller's Airflow credentials so run triggers can
# be made on their behalf.
_deps = [Depends(capture_auth)]
for _router in (
    pipelines_router, runs_router, artifacts_router, schema_router, providers_router,
    sources_router, destinations_router, connections_router, lookup_tables_router,
    dashboards_router, schedules_router, notifications_router, evals_router, me_router,
):
    app.include_router(_router, prefix="/api", dependencies=_deps)

# The UI plugin bundle (plan 066). Absent in dev/tests until the frontend is built.
class _UiFiles(StaticFiles):
    """`dte.umd.js` has a fixed, unhashed name, so every file revalidates;
    without Cache-Control the browser caches it heuristically and keeps
    running the old UI after a rebuild."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


# Installed wheel: dte/ui. Dockerfile.airflow: backend/ui, beside the package.
_ui = next((d for d in (Path(__file__).resolve().parents[1] / "ui",
                         Path(__file__).resolve().parents[2] / "ui") if d.is_dir()), None)
if _ui:
    app.mount("/ui", _UiFiles(directory=_ui, html=True), name="ui")
