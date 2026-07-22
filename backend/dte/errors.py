"""Typed exception hierarchy.

Anything raised by the compiler, source loaders, or engine that is a *user*
mistake (bad field ref, missing lookup, unsupported type coercion) should
inherit from `DTEUserError` and will be surfaced as HTTP 422 by the global
handler in `dte/api/main.py`.

Anything that's a platform fault (DuckDB crashed, S3 unreachable after retries)
should inherit from `DTEPlatformError` and surfaces as 500.

Keep the hierarchy shallow. Add a new subclass only when a route or the
frontend needs to branch on the class.
"""
from __future__ import annotations


class DTEError(Exception):
    """Root class. Never raise directly — raise a subclass."""

    http_status: int = 500
    code: str = "dte_error"


class DTEUserError(DTEError):
    http_status = 422
    code = "user_error"


class DTEPlatformError(DTEError):
    http_status = 500
    code = "platform_error"


class CompilerError(DTEUserError):
    code = "compiler_error"


class SourceLoadError(DTEUserError):
    code = "source_load_error"


class DestinationWriteError(DTEPlatformError):
    code = "destination_write_error"


class RunCancelled(DTEError):
    http_status = 499
    code = "run_cancelled"


class RunTimeout(DTEError):
    http_status = 504
    code = "run_timeout"
