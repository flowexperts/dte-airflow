"""Run interactive source work off the event loop (plan 084).

Schema inference, step schemas, dry-run and preview all load sources and
execute DuckDB synchronously. DTE is mounted inside Airflow's api-server, so
doing that inline in an `async def` route stalls every request on the worker
— run history, Airflow's own UI, health checks — for as long as the source
takes (a paginated REST source: minutes).

A dedicated limiter, not anyio's default one: Airflow's own sync routes share
the default 40-token pool, and a burst of slow previews must not starve them.
Excess interactive work queues here instead.

Keep the DuckDB connection's whole life (create, load, compile, execute)
inside one `run_interactive` call: DuckDB results crossing threads is the
macOS segfault `tests/CLAUDE.md` describes.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from functools import partial

import anyio
import anyio.to_thread
from fastapi import HTTPException

from dte.config import get_settings

# Rows an eager source (rest_api, mongodb) loads for the editor. Runs read
# everything; schema, step schemas and previews read this much.
SAMPLE_ROWS = int(os.environ.get("DTE_SAMPLE_ROWS", "1000"))

LIMITER = anyio.CapacityLimiter(int(os.environ.get("DTE_INTERACTIVE_CONCURRENCY", "4")))


async def run_interactive[T](fn: Callable[..., T], *args, **kwargs) -> T:
    """504 after `preview_timeout_seconds` (plan 086). The worker thread
    can't be killed, so it is abandoned and finishes in the background.
    # ponytail: anyio frees the limiter slot on abandon, so repeated timeouts
    # can run more than DTE_INTERACTIVE_CONCURRENCY threads; interrupt the
    # DuckDB connection on timeout if that bites."""
    timeout = get_settings().preview_timeout_seconds
    try:
        with anyio.fail_after(timeout):
            return await anyio.to_thread.run_sync(
                partial(fn, *args, **kwargs), limiter=LIMITER, abandon_on_cancel=True)
    except TimeoutError:
        raise HTTPException(status_code=504, detail=f"timed out after {timeout:g}s") from None
