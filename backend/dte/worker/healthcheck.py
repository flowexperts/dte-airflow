"""Liveness probe for the worker process.

The worker shares an image with the API, and the image's `HEALTHCHECK` probes
`http://127.0.0.1:8001/healthz`. The worker serves no HTTP, so it inherited a
check it could never pass and reported `unhealthy` for its entire life — on
every `docker compose ps`, in every deployment dashboard. A probe that is
always red is worse than none: it trains everyone to ignore the column that is
supposed to tell them something is wrong.

What actually matters for a worker is whether it can reach the queue. The
process being alive is already covered — it is the container's PID 1, so if it
dies the container exits. Postgres reachability is the part that can fail
silently while the process stays up.
"""

from __future__ import annotations

import asyncio
import os
import sys


async def check(database_url: str | None = None) -> tuple[bool, str]:
    """Return `(healthy, detail)`.

    Detail is returned rather than logged so the failure reason lands in
    `docker inspect`'s health log, which is where anyone debugging looks
    first.
    """
    url = database_url if database_url is not None else os.getenv("DATABASE_URL")
    if not url:
        return False, "DATABASE_URL is not set"

    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
    except Exception as exc:  # pragma: no cover - import failure is fatal anyway
        return False, f"sqlalchemy unavailable: {exc}"

    # A fresh engine per probe, disposed immediately: the probe must not hold
    # a pooled connection open between runs, or a worker at its connection
    # ceiling would be kept there by its own healthcheck.
    engine = create_async_engine(url, poolclass=None, pool_pre_ping=False)
    try:
        async with engine.connect() as conn:
            # The queue table, not just `SELECT 1` — a database that is up but
            # has not been migrated cannot run jobs, and that is precisely the
            # startup-order bug this probe should catch.
            await conn.execute(text("SELECT 1 FROM procrastinate_jobs LIMIT 1"))
        return True, "queue reachable"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        await engine.dispose()


def main() -> int:
    healthy, detail = asyncio.run(check())
    print(detail)
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
