"""The `viz` pipeline type — a pipeline that draws instead of writing (plan 064).

A dashboard tile reads rows from `GET /pipelines/{id}/preview`, which compiles
and executes without touching a writer. So the pipeline feeding a tile has no
destination to name, and requiring one would mean inventing a throwaway JSON
file per chart just to satisfy validation.

`quality` and `eval` already had exactly this property, and the check for it
was copy-pasted at five call sites. `viz` is the third member of that set,
which is why the check now lives in one predicate: the failure mode of the
copies is a type that saves fine and then 422s at preview, in *one* of the
five places, long after the builder said it was valid.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.pipeline import DestinationCreate, Pipeline, SourceCreate


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client(fake_stores, sample_json_file):
    c = TestClient(app)
    _run(fake_stores["source"].save(SourceCreate(
        id="orders", connection_id="local_fs", source_type="filesystem",
        config={"bucket_url": sample_json_file, "file_glob": ""}, table="orders",
    )))
    _run(fake_stores["destination"].save(DestinationCreate(
        id="out", connection_id="local_fs",
        config={"type": "json_file", "path": "/tmp/out.json"},
    )))
    return c


def _body(**over):
    body = {
        "id": "chart-src", "name": "Chart source", "sources": ["orders"],
        "steps": [], "pipeline_type": "viz", "output_id": None,
    }
    body.update(over)
    return body


class TestVizNeedsNoDestination:
    def test_creates_without_an_output_id(self, client):
        r = client.post("/api/pipelines", json=_body())
        assert r.status_code == 200, r.text

    def test_transform_still_requires_one(self, client):
        """The predicate must not have widened to "nothing needs a
        destination" — that would let a transform pipeline save and then
        fail at write time, which is the whole reason the check exists."""
        r = client.post("/api/pipelines", json=_body(pipeline_type="transform"))
        assert r.status_code == 422
        assert "Destination not found" in str(r.json()["detail"])

    def test_previews_without_an_output_id(self, client, fake_stores):
        """Preview is the dashboard's data path. It carried its own copy of
        the destination check, so a viz pipeline could save and still 422
        on the only endpoint a tile ever calls."""
        client.post("/api/pipelines", json=_body())
        r = client.get("/api/pipelines/chart-src/preview?limit=5")
        assert r.status_code == 200, r.text
        assert r.json()["error"] is None
        assert len(r.json()["rows"]) == 3

    def test_dry_run_without_an_output_id(self, client):
        r = client.post("/api/pipelines/dry-run?limit=5", json=_body())
        assert r.status_code == 200, r.text
        assert r.json()["error"] is None


class TestVizRoundTrips:
    def test_type_survives_a_read(self, client, fake_stores):
        client.post("/api/pipelines", json=_body())
        assert _run(fake_stores["pipeline"].get("chart-src")).pipeline_type == "viz"

    def test_type_survives_an_update(self, client, fake_stores):
        """A transform pipeline converted to viz must stay viz. The postgres
        upsert used to omit `pipeline_type` from its ON CONFLICT set, so this
        passed against the fake store and silently did nothing against a real
        database — see test_store_postgres for the other half."""
        _run(fake_stores["pipeline"].save(Pipeline(
            id="convert-me", name="Convert", sources=["orders"], steps=[],
            output_id="out", pipeline_type="transform",
        )))
        r = client.put("/api/pipelines/convert-me", json=_body(
            id="convert-me", name="Convert",
        ))
        assert r.status_code == 200, r.text
        assert _run(fake_stores["pipeline"].get("convert-me")).pipeline_type == "viz"


class TestBlankIdMeansGenerate:
    """`{"id": ""}` must mean "server, name it" — as it already does for
    Source, Destination, LookupTable and Dashboard.

    Without the validator the empty string is written as the primary key.
    The row then exists and is listed, but is unreachable: `/api/pipelines/`
    is not a route, so `DELETE /api/pipelines/` 307s and the only way to
    remove it is SQL. Nothing in the UI shows it, because the builder strips
    `id` before posting — so this only reproduces from the API.
    """

    def test_blank_id_gets_a_generated_one(self, client, fake_stores):
        r = client.post("/api/pipelines", json=_body(id=""))
        assert r.status_code == 200, r.text
        new_id = r.json()["id"]
        assert new_id, "server must generate an id, not accept the blank"
        assert _run(fake_stores["pipeline"].get(new_id)) is not None

    def test_whitespace_id_gets_a_generated_one(self, client):
        r = client.post("/api/pipelines", json=_body(id="   "))
        assert r.status_code == 200, r.text
        assert r.json()["id"].strip()

    def test_an_explicit_id_is_still_honoured(self, client, fake_stores):
        r = client.post("/api/pipelines", json=_body(id="my-own-id"))
        assert r.status_code == 200, r.text
        assert r.json()["id"] == "my-own-id"
