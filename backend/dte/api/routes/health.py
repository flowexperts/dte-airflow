"""Liveness + readiness probes."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from dte.api.deps import _session_factory

router = APIRouter()


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/readyz")
async def readyz():
    """Ready when we can round-trip a query against Postgres."""
    try:
        factory = _session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        return {"status": "not_ready", "detail": str(e)}
    return {"status": "ready"}
