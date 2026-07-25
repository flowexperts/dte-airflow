"""Unit tests: verify that connection PUT and DELETE routes call pool eviction.

Uses the fake store + httpx.AsyncClient pattern from conftest.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from dte.api.main import app
from dte.models.pipeline import ConnectionBase


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(fake_stores):
    """Async httpx client bound to the ASGI app.  `fake_stores` is the autouse
    fixture from conftest; we just need it to have run before we issue requests."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _conn_store(fake_stores):
    return fake_stores["connection"]


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connection_update_evicts_mongo_pool(client, fake_stores):
    """PUT /api/connections/{id} must call mongo_pool.evict(conn_id)."""
    conn_store = _conn_store(fake_stores)
    conn = ConnectionBase(
        id="c-update-evict",
        connection_type="mongodb",
        credentials={"url": "mongodb://localhost/"},
    )
    await conn_store.save(conn)

    with patch("dte.api.routes.connections.mongo_pool.evict", new_callable=AsyncMock) as mock_evict:
        resp = await client.put(
            "/api/connections/c-update-evict",
            json={
                "id": "c-update-evict",
                "connection_type": "mongodb",
                "credentials": {"url": "mongodb://localhost/"},
            },
        )
    assert resp.status_code == 200
    mock_evict.assert_awaited_once_with("c-update-evict")


@pytest.mark.asyncio
async def test_connection_delete_evicts_mongo_pool(client, fake_stores):
    """DELETE /api/connections/{id} must call mongo_pool.evict(conn_id)."""
    conn_store = _conn_store(fake_stores)
    conn = ConnectionBase(
        id="c-delete-evict",
        connection_type="mongodb",
        credentials={"url": "mongodb://localhost/"},
    )
    await conn_store.save(conn)

    with patch("dte.api.routes.connections.mongo_pool.evict", new_callable=AsyncMock) as mock_evict:
        resp = await client.delete("/api/connections/c-delete-evict")
    assert resp.status_code == 204
    mock_evict.assert_awaited_once_with("c-delete-evict")
