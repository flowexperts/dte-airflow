"""Unit tests for BackendRegistry — per-request cache of ibis backends
keyed by Connection.id. Ensures filesystem-family sources share one DuckDB
and DB sources share a native backend per connection."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import ibis
import pytest

from dte.engine.backend_registry import BackendRegistry
from dte.models.pipeline import Connection


def _conn(id: str, ctype: str, creds: dict | None = None) -> Connection:
    return Connection(id=id, connection_type=ctype, credentials=creds or {})


def test_duckdb_returns_provided_backend():
    con = ibis.duckdb.connect()
    reg = BackendRegistry(duckdb_con=con)
    assert reg.duckdb() is con


def test_duckdb_lazily_opens_when_not_provided():
    reg = BackendRegistry()
    a = reg.duckdb()
    b = reg.duckdb()
    assert a is b
    assert type(a).__name__ == "Backend"  # ibis DuckDB backend


def test_for_connection_caches_per_id(monkeypatch):
    """Two calls with the same connection.id return the same backend
    instance. Two different ids get separate backends."""
    reg = BackendRegistry()
    mock_a = MagicMock(name="backend_a")
    mock_b = MagicMock(name="backend_b")
    calls: list[str] = []

    def fake_opener(conn, creds):
        calls.append(conn.id)
        return mock_a if conn.id == "a" else mock_b

    monkeypatch.setattr("dte.engine.backend_registry._open_ibis_backend", fake_opener)

    conn_a = _conn("a", "postgres", {"url": "postgresql://x"})
    conn_b = _conn("b", "postgres", {"url": "postgresql://y"})

    assert reg.for_connection(conn_a, conn_a.credentials) is mock_a
    assert reg.for_connection(conn_a, conn_a.credentials) is mock_a  # cached
    assert reg.for_connection(conn_b, conn_b.credentials) is mock_b
    # opener called exactly twice, one per unique id
    assert calls == ["a", "b"]


def test_open_postgres_uses_url_parts(monkeypatch):
    from dte.engine import backend_registry as br

    captured: dict = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return MagicMock(name="pg")

    monkeypatch.setattr("ibis.postgres.connect", fake_connect)
    br._open_postgres({"url": "postgresql://u:p@dbhost:6543/mydb"})

    assert captured["host"] == "dbhost"
    assert captured["port"] == 6543
    assert captured["user"] == "u"
    assert captured["password"] == "p"
    assert captured["database"] == "mydb"


def test_open_sqlite_strips_scheme(monkeypatch):
    from dte.engine import backend_registry as br

    captured: dict = {}

    def fake_connect(path):
        captured["path"] = path
        return MagicMock(name="sqlite")

    monkeypatch.setattr("ibis.sqlite.connect", fake_connect)
    # SQLAlchemy convention: sqlite:///relative → 'relative', sqlite:////abs → '/abs'.
    br._open_sqlite({"url": "sqlite:////tmp/x.db"})
    assert captured["path"] == "/tmp/x.db"


def test_open_snowflake_without_extra_raises_helpfully(monkeypatch):
    """No snowflake.connector installed → clear extras hint, not a bare
    ModuleNotFoundError."""
    from dte.engine import backend_registry as br

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def blocked_import(name, *args, **kwargs):
        if name == "snowflake.connector" or name.startswith("snowflake."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=blocked_import):
        with pytest.raises(RuntimeError, match="snowflake-source"):
            br._open_snowflake({"url": "snowflake://u:p@acct"})


def test_open_unknown_connection_type_raises():
    from dte.engine import backend_registry as br

    conn = _conn("mystery", "mongodb", {})
    with pytest.raises(NotImplementedError, match="No native ibis backend"):
        br._open_ibis_backend(conn, {})
