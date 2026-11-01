"""Offset paging on GET /api/pipelines/{id}/runs.

A pipeline with hundreds of runs was unreachable past the first page: the
route took `limit` only, so the UI could widen the window but never move it.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def seeded(fake_stores):
    r_store = fake_stores["run"]
    for _ in range(25):
        _run(r_store.create("p_paged"))
    return r_store


def test_store_offset_moves_the_window(seeded):
    first = _run(seeded.list_for_pipeline("p_paged", limit=10))
    second = _run(seeded.list_for_pipeline("p_paged", limit=10, offset=10))

    assert len(first) == 10
    assert len(second) == 10
    assert {r["id"] for r in first}.isdisjoint({r["id"] for r in second})


def test_store_offset_past_the_end_is_empty(seeded):
    assert _run(seeded.list_for_pipeline("p_paged", limit=10, offset=99)) == []


def test_revisions_store_offset(fake_stores):
    """Revisions had the same limit-only shape as runs."""
    from dte.models.pipeline import Pipeline, PipelineRevision

    store = fake_stores["pipeline_revision"]
    for i in range(15):
        _run(
            store.save(
                PipelineRevision(
                    id=f"rev-{i:03d}",
                    pipeline_id="p_paged",
                    config={"id": "p_paged", "name": "x", "steps": []},
                    changed_by="tester",
                    summary=f"edit {i}",
                )
            )
        )

    first = _run(store.list_for_pipeline("p_paged", limit=5))
    second = _run(store.list_for_pipeline("p_paged", limit=5, offset=5))

    assert len(first) == 5
    assert len(second) == 5
    assert {r.id for r in first}.isdisjoint({r.id for r in second})
    assert _run(store.list_for_pipeline("p_paged", limit=5, offset=99)) == []


def test_revisions_route_accepts_offset(fake_stores):
    from dte.models.pipeline import Pipeline, PipelineRevision

    _run(
        fake_stores["pipeline"].save(
            Pipeline(id="p_rev_paged", name="paged", steps=[])
        )
    )
    store = fake_stores["pipeline_revision"]
    for i in range(15):
        _run(
            store.save(
                PipelineRevision(
                    id=f"r2-{i:03d}",
                    pipeline_id="p_rev_paged",
                    config={"id": "p_rev_paged", "name": "x", "steps": []},
                    changed_by="tester",
                    summary=f"edit {i}",
                )
            )
        )

    with TestClient(app) as client:
        page1 = client.get("/api/pipelines/p_rev_paged/revisions?limit=5&offset=0")
        page2 = client.get("/api/pipelines/p_rev_paged/revisions?limit=5&offset=5")

    assert page1.status_code == 200
    assert page2.status_code == 200
    ids1 = {r["id"] for r in page1.json()}
    ids2 = {r["id"] for r in page2.json()}
    assert len(ids1) == 5 and len(ids2) == 5
    assert ids1.isdisjoint(ids2)
