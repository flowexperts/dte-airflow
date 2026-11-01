"""Total counts on the paginated list endpoints.

Offset alone lets a client walk forward blindly — it can't say "page 3 of 12"
or know it has reached the end except by getting a short page. The count
rides in `X-Total-Count` rather than an envelope so no existing response
shape changes.

Runs are the exception (plan 087): Airflow's grid is the run history, the DTE
Runs tab shows only the latest few, and counting meant reading every dag run
of the pipeline from Airflow on each request.
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


def test_revision_store_counts_only_its_pipeline(seeded_revs):
    assert _run(seeded_revs.count_for_pipeline("p_count")) == 7
    assert _run(seeded_revs.count_for_pipeline("nope")) == 0


def test_runs_route_returns_latest_without_a_count(seeded_runs):
    with TestClient(app) as client:
        res = client.get("/api/pipelines/p_count/runs?limit=10")
    assert res.status_code == 200
    assert len(res.json()) == 10
    assert "x-total-count" not in res.headers


def test_revisions_route_sets_total_count_header(seeded_revs):
    with TestClient(app) as client:
        res = client.get("/api/pipelines/p_count/revisions?limit=5&offset=0")
    assert res.status_code == 200
    assert res.headers["x-total-count"] == "7"


