"""Mongo client pool.

Keyed by Connection.id (never by plaintext URL).  Under the
DTE_CONNECTION_POOL_ENABLED feature flag (default: false).

See plans/028-connection-pooling.md — Mongo section.
"""
from __future__ import annotations

import asyncio
import os

try:
    from pymongo import MongoClient
except ImportError:  # pragma: no cover — pymongo is an optional dep
    MongoClient = None  # type: ignore[assignment,misc]

# Feature flag — flip to "true" after a week of dogfooding.
_pool_enabled: bool = os.getenv("DTE_CONNECTION_POOL_ENABLED", "false").lower() in ("1", "true", "yes")

_clients: dict[str, "_MongoClient"] = {}
_lock = asyncio.Lock()


def reset_pool() -> None:
    """Empty the pool without closing clients.  Test utility only."""
    _clients.clear()


async def get_mongo_client(conn):
    """Return a cached MongoClient for *conn*.

    When the pool is disabled every call returns a fresh client.
    When the pool is enabled the client is created once per connection id
    and reused for all subsequent calls.

    Parameters
    ----------
    conn:
        A Connection-like object with `.id` (str) and
        `.credentials["url"]` (str).
    """
    if not _pool_enabled:
        return MongoClient(conn.credentials["url"], appname="dte")

    async with _lock:
        client = _clients.get(conn.id)
        if client is None:
            client = MongoClient(conn.credentials["url"], appname="dte")
            _clients[conn.id] = client
        return client


async def evict(conn_id: str) -> None:
    """Remove *conn_id* from the pool and close its client.

    Safe to call with an id that is not in the pool — it is a no-op.
    """
    async with _lock:
        client = _clients.pop(conn_id, None)
    if client is not None:
        client.close()


async def close_all() -> None:
    """Close every pooled client.  Called on app shutdown."""
    async with _lock:
        items = list(_clients.items())
        _clients.clear()
    for _, client in items:
        client.close()
