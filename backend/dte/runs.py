"""In-process registry of running pipeline tasks.

Enables `POST /api/runs/{id}/cancel` to reach into the asyncio task started by
`trigger_pipeline`. Registry is process-local — sufficient for single-worker
uvicorn; a multi-worker deployment needs a shared control plane (Redis pub/sub,
Postgres LISTEN/NOTIFY) instead.
"""
from __future__ import annotations

import asyncio

_running: dict[str, asyncio.Task] = {}


def register(run_id: str, task: asyncio.Task) -> None:
    _running[run_id] = task
    task.add_done_callback(lambda _t, rid=run_id: _running.pop(rid, None))


def cancel(run_id: str) -> bool:
    task = _running.get(run_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


def is_running(run_id: str) -> bool:
    task = _running.get(run_id)
    return task is not None and not task.done()
