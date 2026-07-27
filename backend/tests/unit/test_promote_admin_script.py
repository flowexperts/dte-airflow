"""Unit tests for the operator-recovery ``promote_admin`` script."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from scripts.promote_admin import _run


@pytest.fixture
def _stub_store():
    with patch("scripts.promote_admin.PostgresUserStore") as StoreCls, patch(
        "scripts.promote_admin.create_async_engine"
    ), patch("scripts.promote_admin.async_sessionmaker"):
        store = StoreCls.return_value
        yield store


async def test_missing_database_url_returns_2(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert await _run("x@y.com") == 2


async def test_unknown_email_returns_1(monkeypatch, _stub_store):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x/y")
    _stub_store.get_by_email = AsyncMock(return_value=None)
    assert await _run("nope@x.com") == 1


async def test_already_admin_is_noop(monkeypatch, _stub_store):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x/y")

    class _Role:
        id = "admin"

    class _User:
        id = "u1"
        roles = [_Role()]

    _stub_store.get_by_email = AsyncMock(return_value=_User())
    _stub_store.add_role = AsyncMock()
    assert await _run("me@x.com") == 0
    _stub_store.add_role.assert_not_awaited()


async def test_grants_admin_when_missing(monkeypatch, _stub_store):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x/y")

    class _User:
        id = "u2"
        roles = []

    _stub_store.get_by_email = AsyncMock(return_value=_User())
    _stub_store.add_role = AsyncMock()
    assert await _run("op@x.com") == 0
    _stub_store.add_role.assert_awaited_once_with("u2", "admin")
