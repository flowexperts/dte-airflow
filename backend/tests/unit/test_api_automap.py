"""The automap route and the destination-schema route it feeds on."""

import asyncio
import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.api.deps import get_connection_store, get_destination_store
from dte.models.pipeline import Connection
from tests.fakes import FakeConnectionStore, FakeDestinationStore


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client():
    d_store = FakeDestinationStore()
    c_store = FakeConnectionStore()
    _run(c_store.save(Connection(
        id="pg", connection_type="postgres",
        credentials={"url": "postgresql://u:p@localhost:5432/db"},
    )))
    app.dependency_overrides[get_destination_store] = lambda: d_store
    app.dependency_overrides[get_connection_store] = lambda: c_store
    yield TestClient(app), d_store
    app.dependency_overrides.clear()


def test_automap_matches_and_leftovers(client):
    c, _ = client
    r = c.post("/api/schema/automap", json={
        "source_fields": [{"name": "customer_id", "type": "int64"},
                          {"name": "ship_date", "type": "date"},
                          {"name": "legacy_code", "type": "string"}],
        "dest_fields": [{"name": "CustomerID", "type": "int64"},
                        {"name": "shipping_date", "type": "date"},
                        {"name": "tax_region", "type": "string"}],
        "use_llm": False,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    by = {m["dest"]: m for m in body["matches"]}
    assert by["CustomerID"]["source"] == "customer_id"
    assert by["shipping_date"]["via"] == "fuzzy"
    assert by["tax_region"]["source"] is None
    assert body["unmatched_source"] == ["legacy_code"]
    assert body["llm_error"] is None


def test_destination_schema_422_for_file_target(client):
    c, d_store = client
    _run(d_store.save({"id": "d1", "connection_id": "local_fs",
                       "config": {"type": "json_file", "path": "/tmp/out.json"}}))
    r = c.get("/api/destinations/d1/schema")
    assert r.status_code == 422, r.text
    assert "table to introspect" in r.json()["detail"]


def test_destination_schema_404_when_missing(client):
    c, _ = client
    assert c.get("/api/destinations/nope/schema").status_code == 404


def test_destination_schema_reads_the_target_table(client, monkeypatch):
    """The route's schema walk, against a real ibis backend.

    DuckDB stands in for the driver — everything after `_open_ibis_backend`
    (table lookup by schema+name, dtype walk, response shape) is the code
    that actually ships. The compat rules forbid a duckdb-backed
    destination, so this is the closest a test with no live Postgres gets.
    """
    import ibis

    con = ibis.duckdb.connect()
    con.raw_sql("CREATE SCHEMA analytics")
    con.raw_sql(
        "CREATE TABLE analytics.orders ("
        "CustomerID BIGINT, shipping_date DATE, total VARCHAR)"
    )
    monkeypatch.setattr(
        "dte.api.routes.destinations._open_ibis_backend", lambda c, creds: con
    )

    c, d_store = client
    _run(d_store.save({"id": "d2", "connection_id": "pg",
                       "config": {"type": "postgres", "schema": "analytics",
                                  "table": "orders"}}))
    r = c.get("/api/destinations/d2/schema")
    assert r.status_code == 200, r.text
    assert [f["name"] for f in r.json()["fields"]] == [
        "CustomerID", "shipping_date", "total",
    ]


def test_destination_schema_422_on_a_missing_table(client, monkeypatch):
    import ibis

    con = ibis.duckdb.connect()
    monkeypatch.setattr(
        "dte.api.routes.destinations._open_ibis_backend", lambda c, creds: con
    )
    c, d_store = client
    _run(d_store.save({"id": "d3", "connection_id": "pg",
                       "config": {"type": "postgres", "schema": "public",
                                  "table": "not_there"}}))
    r = c.get("/api/destinations/d3/schema")
    assert r.status_code == 422, r.text
