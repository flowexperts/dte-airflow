"""The connection probe delegates to the Airflow provider (plan 074)."""
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.pipeline import Connection
from dte.sources import connection_test as ct


def _conn(kind="postgres"):
    return Connection.model_construct(id="c", connection_type=kind, credentials={})


@pytest.fixture
def airflow(monkeypatch):
    state = {"enabled": True, "result": (True, "Connection successfully tested")}
    monkeypatch.setattr(ct, "_testing_enabled", lambda: state["enabled"])

    def get(conn_id):
        if isinstance(state["result"], Exception):
            raise state["result"]
        return NS(test_connection=lambda: state["result"])

    monkeypatch.setattr(ct, "_airflow_connection", get)
    return state


def test_local_fs_always_ok():
    assert ct.probe_connection(_conn("local_fs"))["ok"] is True


def test_uses_the_providers_test(airflow):
    r = ct.probe_connection(_conn())
    assert (r["ok"], r["detail"]) == (True, "Connection successfully tested")


def test_provider_failure_is_reported(airflow):
    airflow["result"] = (False, "password authentication failed")
    r = ct.probe_connection(_conn())
    assert (r["ok"], r["detail"]) == (False, "password authentication failed")


def test_errors_never_raise(airflow):
    airflow["result"] = RuntimeError("no hook")
    r = ct.probe_connection(_conn())
    assert r["ok"] is False and "no hook" in r["detail"]


def test_respects_airflows_switch(airflow):
    airflow["enabled"] = False
    r = ct.probe_connection(_conn())
    assert r["ok"] is False and "test_connection" in r["detail"]


def test_endpoint_returns_probe_result(fake_stores, airflow):
    import asyncio

    from dte.models.pipeline import Connection

    asyncio.get_event_loop().run_until_complete(fake_stores["connection"].save(Connection(
        id="db", connection_type="postgres", credentials={"url": "postgresql://u:p@h/db"})))
    body = TestClient(app).post("/api/connections/db/test").json()
    assert body["ok"] is True and "elapsed_ms" in body


def test_endpoint_404_when_connection_missing():
    assert TestClient(app).post("/api/connections/nope/test").status_code == 404
