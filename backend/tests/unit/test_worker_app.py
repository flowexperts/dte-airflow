"""Tests for the procrastinate app wiring (plan 046 task 1)."""
from __future__ import annotations

import pytest

from dte.worker.app import get_app, psycopg_dsn


def test_psycopg_dsn_strips_asyncpg_driver():
    assert (
        psycopg_dsn("postgresql+asyncpg://dte:dte@postgres:5432/dte")
        == "postgresql://dte:dte@postgres:5432/dte"
    )


def test_psycopg_dsn_leaves_plain_url_unchanged():
    assert (
        psycopg_dsn("postgresql://dte:dte@postgres:5432/dte")
        == "postgresql://dte:dte@postgres:5432/dte"
    )


def test_get_app_raises_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        get_app()


def test_get_app_builds_without_opening_connection(monkeypatch):
    """Constructing the App must not require a live Postgres connection —
    it only opens a pool lazily via `open_async`."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://dte:dte@nonexistent-host:5432/dte")
    app = get_app()
    from procrastinate import App

    assert isinstance(app, App)


def test_get_app_registers_execute_run_task(monkeypatch):
    from dte.worker.app import EXECUTE_RUN_TASK_NAME

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://dte:dte@nonexistent-host:5432/dte")
    app = get_app()
    assert EXECUTE_RUN_TASK_NAME in app.tasks


def test_get_app_registers_periodic_ticker_when_schedules_enabled(monkeypatch):
    from dte.worker.app import TICK_TASK_NAME
    from dte.worker.scheduler import TICK_TASK_NAME as SCHEDULER_TICK_TASK_NAME

    assert TICK_TASK_NAME == SCHEDULER_TICK_TASK_NAME

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://dte:dte@nonexistent-host:5432/dte")
    monkeypatch.setenv("DTE_SCHEDULES_ENABLED", "true")
    app = get_app()
    assert TICK_TASK_NAME in app.tasks
    assert (TICK_TASK_NAME, "") in app.periodic_registry.periodic_tasks


def test_get_app_does_not_register_ticker_when_schedules_disabled(monkeypatch):
    from dte.worker.app import TICK_TASK_NAME

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://dte:dte@nonexistent-host:5432/dte")
    monkeypatch.delenv("DTE_SCHEDULES_ENABLED", raising=False)
    app = get_app()
    assert TICK_TASK_NAME not in app.tasks
