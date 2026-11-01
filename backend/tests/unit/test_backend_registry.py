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


def test_bigquery_authenticates_with_the_airflow_providers_credentials(monkeypatch):
    import sys
    from types import ModuleType
    from types import SimpleNamespace as NS

    from dte.engine import backend_registry as br

    for m in ("google", "google.cloud", "google.cloud.bigquery"):  # the import guard
        monkeypatch.setitem(sys.modules, m, sys.modules.get(m) or ModuleType(m))
    seen = {}
    monkeypatch.setattr(br, "_gcp_credentials", lambda conn_id: f"creds-of-{conn_id}")
    monkeypatch.setattr(br, "ibis", NS(bigquery=NS(connect=lambda **kw: seen.update(kw) or "con")))
    br._open_bigquery({"url": "bigquery://prj/ds", "conn_id": "gcp"})
    assert seen == {"project_id": "prj", "dataset_id": "ds", "credentials": "creds-of-gcp"}
    # An Airflow connection carries only the project; ibis needs "" (not None)
    # for "no default dataset" or parse_project_and_dataset crashes.
    br._open_bigquery({"url": "bigquery://prj", "conn_id": "gcp"})
    assert seen["dataset_id"] == ""


def _fake_bigquery_module(monkeypatch):
    """A stand-in `google.cloud.bigquery` that records what the opener builds."""
    import sys
    from types import ModuleType

    bq = ModuleType("google.cloud.bigquery")

    class QueryJobConfig:
        def __init__(self, **kw):
            self.kw = kw

    class Client:
        def __init__(self, **kw):
            self.kw = kw

    bq.QueryJobConfig, bq.Client = QueryJobConfig, Client
    for m in ("google", "google.cloud"):
        monkeypatch.setitem(sys.modules, m, sys.modules.get(m) or ModuleType(m))
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", bq)
    sys.modules["google.cloud"].bigquery = bq
    return bq


def test_bigquery_cap_rides_on_the_clients_default_job_config(monkeypatch):
    """Plan 093: every query the backend runs (preview, run, introspection)
    goes through this client, so BigQuery itself refuses past the cap."""
    from types import SimpleNamespace as NS

    from dte.engine import backend_registry as br

    _fake_bigquery_module(monkeypatch)
    seen = {}
    monkeypatch.setattr(br, "_gcp_credentials", lambda conn_id: "creds")
    monkeypatch.setattr(br, "ibis", NS(bigquery=NS(connect=lambda **kw: seen.update(kw) or "con")))
    br._open_bigquery({"url": "bigquery://prj", "conn_id": "gcp", "max_bytes_billed": 1000})
    client = seen["client"]
    assert client.kw["project"] == "prj"
    assert client.kw["credentials"] == "creds"
    assert client.kw["default_query_job_config"].kw == {"maximum_bytes_billed": 1000}


def test_snowflake_statement_timeout_is_a_session_parameter(monkeypatch):
    import sys
    from types import ModuleType
    from types import SimpleNamespace as NS

    from dte.engine import backend_registry as br

    for m in ("snowflake", "snowflake.connector"):
        monkeypatch.setitem(sys.modules, m, sys.modules.get(m) or ModuleType(m))
    seen = {}
    monkeypatch.setattr(br, "ibis", NS(connect=lambda url, **kw: seen.update(url=url, **kw) or "con"))
    br._open_snowflake({"url": "snowflake://u:p@acct/db", "statement_timeout_seconds": 30})
    assert seen == {"url": "snowflake://u:p@acct/db",
                    "session_parameters": {"STATEMENT_TIMEOUT_IN_SECONDS": 30}}
    seen.clear()
    br._open_snowflake({"url": "snowflake://u:p@acct/db"})
    assert seen == {"url": "snowflake://u:p@acct/db"}
