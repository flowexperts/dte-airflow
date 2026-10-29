"""Connections resolve the way Airflow resolves them (plan 074)."""
import asyncio
from types import SimpleNamespace as NS

import pytest

from dte.airflow import connection_store as store


def _conn(conn_id, conn_type):
    return NS(conn_id=conn_id, conn_type=conn_type, host=None, schema=None, login=None,
              password=None, port=None, extra_dejson={},
              get_hook=lambda: NS(get_uri=lambda: "postgresql://u:p@h/db"))


@pytest.fixture
def airflow(monkeypatch):
    conns = {"pg": _conn("pg", "postgres"), "s3": _conn("s3", "aws"),
             "mongo": _conn("mongo", "mongo"), "cache": _conn("cache", "redis")}

    def get(conn_id):
        if conn_id not in conns:
            raise KeyError(conn_id)
        return conns[conn_id]

    monkeypatch.setattr(store, "_get", get)
    monkeypatch.setattr(store, "_all_conn_ids", lambda: sorted(conns))
    # mongo provider not installed
    monkeypatch.setattr(store, "available_kinds", lambda: {"postgres", "s3", "local_fs"})
    return conns


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_list_offers_only_installed_and_mapped(airflow):
    got = run(store.AirflowConnectionStore().list())
    assert [(c.id, c.connection_type, c.credentials) for c in got] == [
        ("pg", "postgres", {}), ("s3", "s3", {})]


def test_get_resolves_through_airflow(airflow):
    c = run(store.AirflowConnectionStore().get("pg"))
    assert c.credentials == {"url": "postgresql://u:p@h/db"}


def test_get_unknown_or_unavailable_is_none(airflow):
    s = store.AirflowConnectionStore()
    assert run(s.get("nope")) is None
    assert run(s.get("mongo")) is None
    assert run(s.get("cache")) is None
