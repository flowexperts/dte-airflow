"""Tests for the connection-probe endpoint + dispatch."""
import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.pipeline import Connection
from dte.sources.connection_test import probe_connection


def test_local_fs_probe_always_ok():
    r = probe_connection(Connection(id="c", connection_type="local_fs", credentials={}))
    assert r["ok"] is True


def test_sql_probe_missing_url_reports_shape_error():
    # sqlite/postgres/mysql/etc all route through _probe_sql_url — with no
    # `url` field the probe fails cleanly.
    conn = Connection(id="c", connection_type="sqlite", credentials={"url": "sqlite:///"})
    conn.credentials = {}  # simulate malformed stored row
    r = probe_connection(conn)
    assert r["ok"] is False
    assert "url" in r["detail"]


def test_sqlite_probe_hits_real_db(tmp_path):
    import sqlite3
    db = tmp_path / "probe.db"
    sqlite3.connect(str(db)).close()
    r = probe_connection(
        Connection(id="c", connection_type="sqlite", credentials={"url": f"sqlite:///{db}"})
    )
    assert r["ok"] is True
    assert r["elapsed_ms"] >= 0


def test_endpoint_returns_probe_result(fake_stores, tmp_path):
    import sqlite3
    db = tmp_path / "probe.db"
    sqlite3.connect(str(db)).close()

    c = TestClient(app)
    c.post("/api/connections", json={
        "id": "db", "connection_type": "sqlite",
        "credentials": {"url": f"sqlite:///{db}"},
    })
    r = c.post("/api/connections/db/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "elapsed_ms" in body


def test_endpoint_404_when_connection_missing():
    c = TestClient(app)
    r = c.post("/api/connections/nope/test")
    assert r.status_code == 404
