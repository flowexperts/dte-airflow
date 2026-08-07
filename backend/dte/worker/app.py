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

import os

from procrastinate import App, PsycopgConnector


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
    return App(connector=connector, import_paths=["dte.worker.tasks"])
