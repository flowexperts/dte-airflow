"""Request-ID + access-log middleware."""
from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from dte.logging import get_logger, request_id_var

_log = get_logger("dte.access")


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
