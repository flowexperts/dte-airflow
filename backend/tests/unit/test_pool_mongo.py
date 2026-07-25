"""Unit tests for the Mongo client pool (dte/sources/pools/mongo.py).

Tests cover:
- cache hit: two calls with the same connection id return the same object
- cache miss: new connection id gets a fresh object
- evict: removes the entry from the pool
- evict on unknown id is a no-op
- pool disabled by default (DTE_CONNECTION_POOL_ENABLED not set)
- pool active when DTE_CONNECTION_POOL_ENABLED=true
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from dte.sources.pools.mongo import evict, get_mongo_client, reset_pool


class _FakeConnection:
    def __init__(self, conn_id: str, url: str = "mongodb://localhost/"):
        self.id = conn_id
        self.credentials = {"url": url}


@pytest.fixture(autouse=True)
def _clean_pool():
    """Reset the module-level dict before and after each test."""
    reset_pool()
    yield
    reset_pool()


@pytest.fixture
def mock_mongo_client():
    """Patch MongoClient so no real TCP connection is made."""
    with patch("dte.sources.pools.mongo.MongoClient") as mock_cls:
        instance = MagicMock()
        mock_cls.return_value = instance
        yield mock_cls, instance


# ---------------------------------------------------------------------------
# Cache hit / miss
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_returns_same_client(mock_mongo_client):
    mock_cls, _ = mock_mongo_client
    conn = _FakeConnection("conn-1")

    with patch("dte.sources.pools.mongo._pool_enabled", True):
        client_a = await get_mongo_client(conn)
        client_b = await get_mongo_client(conn)

    assert client_a is client_b
    # MongoClient constructor called exactly once
    mock_cls.assert_called_once()


@pytest.mark.asyncio
async def test_cache_miss_creates_new_client(mock_mongo_client):
    mock_cls, _ = mock_mongo_client
    # Two *different* instances returned by the mock
    inst_a = MagicMock()
    inst_b = MagicMock()
    mock_cls.side_effect = [inst_a, inst_b]

    conn_a = _FakeConnection("conn-a")
    conn_b = _FakeConnection("conn-b")

    with patch("dte.sources.pools.mongo._pool_enabled", True):
        client_a = await get_mongo_client(conn_a)
        client_b = await get_mongo_client(conn_b)

    assert client_a is inst_a
    assert client_b is inst_b
    assert mock_cls.call_count == 2


# ---------------------------------------------------------------------------
# Eviction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evict_removes_entry(mock_mongo_client):
    mock_cls, instance = mock_mongo_client
    conn = _FakeConnection("conn-evict")

    with patch("dte.sources.pools.mongo._pool_enabled", True):
        await get_mongo_client(conn)
        await evict("conn-evict")

        # Pool now empty → second call creates a fresh client
        fresh = MagicMock()
        mock_cls.return_value = fresh
        client2 = await get_mongo_client(conn)

    assert client2 is fresh
    assert mock_cls.call_count == 2


@pytest.mark.asyncio
async def test_evict_calls_close(mock_mongo_client):
    _, instance = mock_mongo_client
    conn = _FakeConnection("conn-close")

    with patch("dte.sources.pools.mongo._pool_enabled", True):
        await get_mongo_client(conn)
        await evict("conn-close")

    instance.close.assert_called_once()


@pytest.mark.asyncio
async def test_evict_unknown_id_is_noop(mock_mongo_client):
    """evict on an id not in the pool must not raise."""
    await evict("does-not-exist")  # should not raise


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pool_disabled_creates_fresh_client_each_time(mock_mongo_client):
    """When DTE_CONNECTION_POOL_ENABLED is unset (default), every call returns
    a new MongoClient even for the same connection id."""
    mock_cls, _ = mock_mongo_client
    inst_a = MagicMock()
    inst_b = MagicMock()
    mock_cls.side_effect = [inst_a, inst_b]

    conn = _FakeConnection("conn-flag")

    with patch("dte.sources.pools.mongo._pool_enabled", False):
        client_a = await get_mongo_client(conn)
        client_b = await get_mongo_client(conn)

    assert client_a is inst_a
    assert client_b is inst_b
    assert mock_cls.call_count == 2


@pytest.mark.asyncio
async def test_pool_enabled_caches(mock_mongo_client):
    """When the flag is True, the second call is a cache hit."""
    mock_cls, _ = mock_mongo_client
    conn = _FakeConnection("conn-enabled")

    with patch("dte.sources.pools.mongo._pool_enabled", True):
        client_a = await get_mongo_client(conn)
        client_b = await get_mongo_client(conn)

    assert client_a is client_b
    mock_cls.assert_called_once()
