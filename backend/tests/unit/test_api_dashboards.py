"""Dashboard CRUD (plan 064).

Deliberately thin: dashboards are layout rows. There is no execution, no
trigger and no `/data` endpoint — a tile fetches its own pipeline's preview,
so nothing here touches the engine, a source, or a destination.

The permission cases matter more than usual. `dashboard:*` is a brand new
`Permission` value, and the roles table (not the code) is what actually
grants it — migration 038 backfills the seeded roles. These tests cover the
code half; the migration half is verified against a real database.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.api.deps import get_current_user
from dte.models.user import User


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client(fake_stores):
    yield TestClient(app), fake_stores["dashboard"]


def _tile(title="Revenue by region", **over):
    t = {
        "title": title,
        "pipeline_id": "p1",
        "chart": {"kind": "bar", "x": "region", "y": ["revenue"]},
    }
    t.update(over)
    return t


def _body(did="d1", name="Ops", tiles=None):
    return {"id": did, "name": name, "description": None,
            "tiles": tiles if tiles is not None else [_tile()]}


class TestCrud:
    def test_create(self, client):
        c, store = client
        r = c.post("/api/dashboards", json=_body())
        assert r.status_code == 201, r.text
        assert _run(store.get("d1")).name == "Ops"

    def test_create_rejects_a_duplicate_id(self, client):
        c, _ = client
        c.post("/api/dashboards", json=_body())
        assert c.post("/api/dashboards", json=_body()).status_code == 409

    def test_create_rejects_a_duplicate_name(self, client):
        """UNIQUE (name) — people identify a dashboard by name,
        and the list is unusable with two called the same thing."""
        c, _ = client
        c.post("/api/dashboards", json=_body())
        r = c.post("/api/dashboards", json=_body(did="d2", name="Ops"))
        assert r.status_code == 409

    def test_get(self, client):
        c, _ = client
        c.post("/api/dashboards", json=_body())
        r = c.get("/api/dashboards/d1")
        assert r.status_code == 200
        assert r.json()["tiles"][0]["chart"]["kind"] == "bar"

    def test_get_missing_is_404(self, client):
        assert client[0].get("/api/dashboards/nope").status_code == 404

    def test_list(self, client):
        c, _ = client
        c.post("/api/dashboards", json=_body())
        c.post("/api/dashboards", json=_body(did="d2", name="Sales"))
        assert len(c.get("/api/dashboards").json()) == 2

    def test_update(self, client):
        c, store = client
        c.post("/api/dashboards", json=_body())
        r = c.put("/api/dashboards/d1", json=_body(name="Ops v2", tiles=[]))
        assert r.status_code == 200, r.text
        got = _run(store.get("d1"))
        assert got.name == "Ops v2"
        assert got.tiles == []

    def test_update_rejects_an_id_mismatch(self, client):
        c, _ = client
        c.post("/api/dashboards", json=_body())
        assert c.put("/api/dashboards/d1", json=_body(did="d2")).status_code == 400

    def test_update_missing_is_404(self, client):
        assert client[0].put("/api/dashboards/nope", json=_body(did="nope")).status_code == 404

    def test_delete(self, client):
        c, store = client
        c.post("/api/dashboards", json=_body())
        assert c.delete("/api/dashboards/d1").status_code == 204
        assert _run(store.get("d1")) is None

    def test_delete_missing_is_404(self, client):
        assert client[0].delete("/api/dashboards/nope").status_code == 404


class TestValidation:
    def test_rejects_a_bar_tile_with_no_value_field(self, client):
        c, _ = client
        bad = _tile(chart={"kind": "bar", "x": "region", "y": []})
        assert c.post("/api/dashboards", json=_body(tiles=[bad])).status_code == 422

    def test_rejects_duplicate_tile_titles(self, client):
        c, _ = client
        r = c.post("/api/dashboards", json=_body(tiles=[_tile(), _tile()]))
        assert r.status_code == 422

    def test_accepts_a_dashboard_with_no_tiles(self, client):
        """The editor saves the dashboard before adding tiles to it."""
        assert client[0].post("/api/dashboards", json=_body(tiles=[])).status_code == 201


def _viewer() -> User:
    """A user holding only `dashboard:read`.

    """
    u = User(id="v", email="v@example.com", permissions=["dashboard:read"])
    return u


class TestPermissions:
    def test_viewer_cannot_create(self, client):
        c, _ = client
        app.dependency_overrides[get_current_user] = _viewer
        try:
            assert c.post("/api/dashboards", json=_body()).status_code == 403
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_viewer_can_read(self, client):
        c, _ = client
        c.post("/api/dashboards", json=_body())
        app.dependency_overrides[get_current_user] = _viewer
        try:
            assert c.get("/api/dashboards/d1").status_code == 200
        finally:
            app.dependency_overrides.pop(get_current_user, None)
