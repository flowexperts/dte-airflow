"""Request-ID + access-log middleware, and tenant-context middleware."""
from __future__ import annotations

import time
import uuid

import jwt as _jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from dte.logging import get_logger, request_id_var
from dte.tenancy import set_current_tenant, tenant_context_var

_log = get_logger("dte.access")

# Paths that are accessible without authentication — the middleware will NOT
# enforce the tenant JWT check for these.  Must match exactly what the router
# registers (no trailing slash, no query string).
_PUBLIC_PATHS: frozenset[str] = frozenset({
    "/healthz",
    "/readyz",
    "/api/auth/login",
    "/api/auth/register",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/metrics",
})


class TenantContextMiddleware(BaseHTTPMiddleware):
    """Extract the tenant_id from the incoming JWT and store it in a contextvar.

    Behaviour when ``DTE_MULTI_TENANT_ENABLED`` is False (default):
      - Sets the contextvar to ``"default"`` unconditionally.
      - Does **not** inspect the Authorization header.
      - Never returns 401.

    Behaviour when ``DTE_MULTI_TENANT_ENABLED`` is True:
      - Public paths (see ``_PUBLIC_PATHS``): sets ``"default"``, continues.
      - Protected paths without a Bearer token → 401.
      - Protected paths with an invalid/expired token → 401.
      - Valid token → reads the ``tenant`` claim (defaults to ``"default"``
        for legacy tokens), stores in the contextvar, continues.

    The contextvar lives for the duration of the request.  Background tasks
    spawned inside the request handler inherit the value via
    ``contextvars.copy_context()`` (see pipelines.py ``trigger_pipeline``).
    """

    async def dispatch(self, request: Request, call_next):
        from dte.config import get_settings
        from dte.security.jwt import decode_access_token

        settings = get_settings()

        if not settings.multi_tenant_enabled:
            # Single-tenant / feature-off: always "default", no enforcement.
            ctxtoken = set_current_tenant("default")
            try:
                return await call_next(request)
            finally:
                tenant_context_var.reset(ctxtoken)

        # Multi-tenant is enabled.
        path = request.url.path

        if path in _PUBLIC_PATHS:
            # Public paths skip JWT enforcement but still set the contextvar.
            ctxtoken = set_current_tenant("default")
            try:
                return await call_next(request)
            finally:
                tenant_context_var.reset(ctxtoken)

        # Protected path — require a valid Bearer token.
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        raw_token = auth_header[len("Bearer "):]
        try:
            payload = decode_access_token(raw_token)
        except _jwt.PyJWTError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or expired token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        tenant_id: str = payload.get("tenant", "default") or "default"
        ctxtoken = set_current_tenant(tenant_id)
        try:
            return await call_next(request)
        finally:
            tenant_context_var.reset(ctxtoken)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            _log.exception(
                "request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "elapsed_ms": elapsed_ms,
                },
            )
            raise
        else:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            level = "info" if response.status_code < 500 else "error"
            getattr(_log, level)(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "elapsed_ms": elapsed_ms,
                },
            )
            response.headers["x-request-id"] = rid
            return response
        finally:
            request_id_var.reset(token)
