"""Global FastAPI exception handlers.

Turn typed `DTEError` subclasses into consistent JSON error responses,
and log unhandled exceptions with request context.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from dte.errors import DTEError, DTEUserError
from dte.logging import get_logger

_log = get_logger("dte.errors")


def _body(err: DTEError) -> dict:
    return {"error": {"code": err.code, "message": str(err) or err.code}}


async def _dte_error_handler(request: Request, exc: DTEError) -> JSONResponse:
    if isinstance(exc, DTEUserError):
        _log.info("user error", extra={"code": exc.code, "path": request.url.path})
    else:
        _log.error("platform error", extra={"code": exc.code, "path": request.url.path}, exc_info=exc)
    return JSONResponse(status_code=exc.http_status, content=_body(exc))


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    _log.exception("unhandled exception", extra={"path": request.url.path})
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "Internal server error"}},
    )


def register(app: FastAPI) -> None:
    app.add_exception_handler(DTEError, _dte_error_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
