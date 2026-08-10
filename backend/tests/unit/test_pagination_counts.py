"""Total counts on the paginated list endpoints.

Offset alone lets a client walk forward blindly — it can't say "page 3 of 12"
or know it has reached the end except by getting a short page. The count
rides in `X-Total-Count` rather than an envelope so no existing response
shape changes.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.pipeline import Pipeline, PipelineRevision


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def seeded_runs(fake_stores):
    store = fake_stores["run"]
    for _ in range(23):
        _run(store.create("p_count"))
    return store


@pytest.fixture
def seeded_revs(fake_stores):
    # The revisions route checks the pipeline exists before listing.
    _run(
        fake_stores["pipeline"].save(
            Pipeline(id="p_count", name="counted", steps=[])
        )
    )
    store = fake_stores["pipeline_revision"]
    for i in range(7):
        _run(
            store.save(
                PipelineRevision(
                    id=f"rc-{i:03d}",
                    pipeline_id="p_count",
                    config={"id": "p_count", "name": "x", "steps": []},
                    changed_by="tester",
                    summary=f"edit {i}",
                )
            )
        )
    return store


def test_run_store_counts_only_its_pipeline(seeded_runs):
    _run(seeded_runs.create("other_pipeline"))
    assert _run(seeded_runs.count_for_pipeline("p_count")) == 23


def test_revision_store_counts_only_its_pipeline(seeded_revs):
    assert _run(seeded_revs.count_for_pipeline("p_count")) == 7
    assert _run(seeded_revs.count_for_pipeline("nope")) == 0


def test_runs_route_sets_total_count_header(seeded_runs):
    with TestClient(app) as client:
        res = client.get("/api/pipelines/p_count/runs?limit=10&offset=10")
    assert res.status_code == 200
    assert len(res.json()) == 10
    # The count is of everything, not of the page.
    assert res.headers["x-total-count"] == "23"


def test_revisions_route_sets_total_count_header(seeded_revs):
    with TestClient(app) as client:
        res = client.get("/api/pipelines/p_count/revisions?limit=5&offset=0")
    assert res.status_code == 200
    assert res.headers["x-total-count"] == "7"


def test_total_count_is_readable_cross_origin():
    """A header the browser can't read is the same as no header at all."""
    from dte.api.main import app as fresh_app

    cors = [m for m in fresh_app.user_middleware if "CORS" in str(m)]
    assert cors, "CORS middleware not installed"
    exposed = cors[0].kwargs.get("expose_headers") or []
    assert "X-Total-Count" in exposed
