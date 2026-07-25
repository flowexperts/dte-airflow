import os

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from dte.admin import mount_admin
from dte.api.deps import get_current_user
from dte.api.limiter import limiter
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
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# FastAPI auto-instrumentation is opt-in via DTE_TRACING_ENABLED. Off in tests.
if os.getenv("DTE_TRACING_ENABLED", "0") == "1":
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)

app.add_middleware(SlowAPIMiddleware)
app.add_middleware(RequestContextMiddleware)

# Prometheus /metrics endpoint exposing the domain metrics defined in
# dte.metrics (emitted from _execute_pipeline). HTTP RED metrics
# (request rate + latency + status) are TODO — prometheus-fastapi-instrumentator
# 7.1.0 crashes on FastAPI 0.115+ _IncludedRouter; revisit when upstream fixes.
# See plan 031.
app.mount("/metrics", make_asgi_app())

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
