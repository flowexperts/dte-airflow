"""Worker process entrypoint — `python -m dte.worker` (plan 046 task 6).

Runs a procrastinate worker pool that dequeues and executes `execute_run`
jobs, the same task `_enqueue_run` (dte/api/routes/pipelines.py) defers
when `DTE_JOB_QUEUE_ENABLED` is on. This is a separate deployable from the
API process — see plan 046's "Deployment topology": `dte-api` stays
stateless/HPA-scaled on request rate, `dte-worker` scales on run
concurrency, and a run's memory ceiling maps 1:1 to this process's
container limit (as opposed to sharing the API process's ceiling with
every concurrent HTTP request).
"""
from __future__ import annotations

import asyncio
import contextlib

from dte.logging import configure_logging, get_logger
from dte.tracing import configure_tracing
from dte.worker.app import get_app
from dte.worker.reaper import run_reaper_loop

_log = get_logger("dte.worker")


async def _run() -> None:
    app = get_app()
    _log.info("worker starting", extra={"tasks": list(app.tasks)})
    async with app.open_async():
        # Local import: dte.api.deps requires DATABASE_URL to exist and
        # imports a good chunk of the FastAPI store wiring — deferred so
        # `get_app()`/module import stay side-effect-free, matching the
        # rest of dte.worker.
        from dte.api.deps import _session_factory

        reaper_task = asyncio.create_task(run_reaper_loop(_session_factory()))
        try:
            await app.run_worker_async()
        finally:
            reaper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reaper_task


def main() -> None:
    configure_logging()
    configure_tracing()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
