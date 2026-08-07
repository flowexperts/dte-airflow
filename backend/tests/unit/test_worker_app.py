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
