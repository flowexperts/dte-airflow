from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dte.admin import mount_admin
from dte.api.deps import get_current_user
from dte.api.error_handlers import register as register_error_handlers
from dte.api.middleware import RequestContextMiddleware
from dte.api.routes.auth import router as auth_router
from dte.api.routes.connections import router as connections_router
from dte.api.routes.destinations import router as destinations_router
from dte.api.routes.health import router as health_router
from dte.api.routes.lookup_tables import router as lookup_tables_router
from dte.api.routes.pipelines import router as pipelines_router
from dte.api.routes.runs import router as runs_router
from dte.api.routes.schema import router as schema_router
from dte.api.routes.sources import router as sources_router
from dte.api.routes.users import router as users_router
from dte.config import get_settings
from dte.logging import configure_logging
from dte.tracing import configure_tracing

configure_logging()
configure_tracing()
_settings = get_settings()

app = FastAPI(title="DTE API")

# FastAPI auto-instrumentation is opt-in via DTE_TRACING_ENABLED to keep tests
# quiet. Guarded so it also works if OTel deps happen to be absent.
try:
    import os as _os

    if _os.getenv("DTE_TRACING_ENABLED", "0") == "1":
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
except Exception:  # pragma: no cover
    pass

app.add_middleware(RequestContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

# Health checks stay open.
app.include_router(health_router)

# Auth routes stay open (login / register). /auth/me carries its own
# `Depends(get_current_user)`.
app.include_router(auth_router, prefix="/api")

# All other data routes are gated at the router level so no route can be
# added without auth by accident.
_auth = [Depends(get_current_user)]
app.include_router(pipelines_router, prefix="/api", dependencies=_auth)
app.include_router(runs_router, prefix="/api", dependencies=_auth)
app.include_router(schema_router, prefix="/api", dependencies=_auth)
app.include_router(sources_router, prefix="/api", dependencies=_auth)
app.include_router(destinations_router, prefix="/api", dependencies=_auth)
app.include_router(connections_router, prefix="/api", dependencies=_auth)
app.include_router(lookup_tables_router, prefix="/api", dependencies=_auth)
app.include_router(users_router, prefix="/api", dependencies=_auth)

# Mount FastAdmin at /admin when DTE_ADMIN_ENABLED=true. Off by default so
# tests and dev without an admin secret keep working.
mount_admin(app)
