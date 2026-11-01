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

LIMITER = anyio.CapacityLimiter(int(os.environ.get("DTE_INTERACTIVE_CONCURRENCY", "4")))


async def run_interactive[T](fn: Callable[..., T], *args, **kwargs) -> T:
    return await anyio.to_thread.run_sync(partial(fn, *args, **kwargs), limiter=LIMITER)
