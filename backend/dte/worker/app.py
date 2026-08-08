"""Procrastinate job-queue app wiring (plan 046).

Reuses `DATABASE_URL` — the same Postgres instance the SQLAlchemy stores
point at — for the job queue. Procrastinate's async connector is psycopg
(v3), not asyncpg, so `psycopg_dsn()` strips the SQLAlchemy `+asyncpg`
driver qualifier that a plain libpq DSN doesn't understand.

Constructing `get_app()` never opens a connection — `PsycopgConnector`
only creates its pool inside `App.open_async()`. This keeps import-time
side effects at zero, so unit tests can build (and even discard) an App
without a live Postgres instance.
"""
from __future__ import annotations

import asyncio
import os

from procrastinate import App, PsycopgConnector

EXECUTE_RUN_TASK_NAME = "execute_run"
TICK_TASK_NAME = "scheduler_tick"


def psycopg_dsn(database_url: str) -> str:
    """Convert a SQLAlchemy-style DATABASE_URL to a plain libpq DSN.

    SQLAlchemy urls carry a driver qualifier (`postgresql+asyncpg://...`);
    psycopg (and libpq generally) only understands `postgresql://...`.
    Mirrors the `sed 's|+asyncpg||'` done for alembic in docker-compose.yml.
    """
    scheme, _, rest = database_url.partition("://")
    if "+" in scheme:
        scheme = scheme.split("+", 1)[0]
    return f"{scheme}://{rest}"


def get_app() -> App:
    """Build the procrastinate App, wired to DATABASE_URL.

    Not cached (mirrors `dte.config.get_settings`): tests monkeypatch env
    between cases and expect the next call to see the new value. Building
    an App is cheap — it does not open a connection pool.

    Raises RuntimeError if DATABASE_URL is unset, mirroring
    `dte.api.deps._session_factory`.
    """
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. dte's job queue requires Postgres, "
            "same as its stores."
        )
    connector = PsycopgConnector(conninfo=psycopg_dsn(url))
    app = App(connector=connector, import_paths=["dte.worker.tasks"])
    _register_tasks(app)
    return app


def _register_tasks(app: App) -> None:
    """Register every dte job task on a freshly-built App.

    A local import — `dte.worker.tasks` imports `_run_body` from
    `dte.api.routes.pipelines` at module scope, and nothing in this module
    should force that import chain just to build an (unopened) App.
    """
    from dte.config import get_settings
    from dte.worker.tasks import execute_run_job

    app.task(name=EXECUTE_RUN_TASK_NAME)(execute_run_job)

    # Recurring triggers (plan 047) — gated behind DTE_SCHEDULES_ENABLED so
    # a deployment that never uses schedules doesn't pay for an extra
    # minute-tick DB query. Depends on the job queue itself (schedules_enabled
    # implies job_queue_enabled — see Settings.schedules_enabled docstring);
    # this only controls whether the *ticker* runs, not whether jobs can be
    # deferred at all.
    if get_settings().schedules_enabled:
        from dte.worker.scheduler import tick_task

        tick = app.task(name=TICK_TASK_NAME)(tick_task)
        app.periodic(cron="* * * * *")(tick)


_running_app: App | None = None
_running_app_lock = asyncio.Lock()


async def get_running_app() -> App:
    """Return a process-wide App with its connection pool already open.

    `get_app()` builds a fresh, unopened App on every call by design (cheap,
    side-effect-free, good for tests — see its docstring). Deferring a job
    needs an actually-open psycopg pool, and opening one per HTTP request
    would be wasteful and would leak connections, so this caches one opened
    App for the life of the process instead — the async equivalent of
    `dte.api.deps._session_factory`'s `@lru_cache`.
    """
    global _running_app
    if _running_app is not None:
        return _running_app
    async with _running_app_lock:
        if _running_app is None:
            app = get_app()
            await app.open_async()
            _running_app = app
        return _running_app


async def close_running_app() -> None:
    """Close and forget the singleton opened App.

    Called on app shutdown (see `dte.api.main`'s lifespan) and by tests
    that need a fresh pool after monkeypatching DATABASE_URL.
    """
    global _running_app
    if _running_app is not None:
        await _running_app.close_async()
        _running_app = None
