"""Finding a comparison you already ran (plan 053).

`/pipelines/{id}/compare?sweep=<id>` shipped reachable only from the
redirect fired once at launch. Navigate away and the comparison was gone
unless you had kept the URL — the same "creatable and reachable from
nowhere" failure this plan was written to fix in plan 051's surfaces.

Two things make the listing non-trivial, and both are about the variant
namespace:

**A sweep's runs are filed under its cells, not under the pipeline you
swept.** Cells are separate pipelines (`root__digest`), so listing runs by
`pipeline_id = root` finds nothing at all.

**A sweep launched from a variant belongs to the root too.** Otherwise
comparisons scatter across cryptic ids and the page you would look on is
the one place they are not.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.eval import EvalSetBase
from dte.models.pipeline import Pipeline, SourceCreate


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _steps():
    return [
        {"op": "extract", "source_field": "path", "provider": "pdfplumber",
         "granularity": "page", "output_field": "content", "params": {}},
        {"op": "structure", "input_field": "content", "provider": "regex",
         "on_error": "null", "params": {},
         "model": {"instructions": "", "fields": [
             {"name": "total", "type": "float", "pattern": r"(\d+)"}]}},
    ]


@pytest.fixture
def client(fake_stores):
    c = TestClient(app)
    _run(fake_stores["source"].save(SourceCreate(
        id="docs", connection_id="local_fs", source_type="documents",
        config={"bucket_url": "/tmp", "file_glob": "**/*.pdf"}, table="docs",
    )))
    _run(fake_stores["eval_set"].save(EvalSetBase(
        id="set1", name="Invoices", source_id="docs",
        field_specs=[{"name": "total", "type": "numeric"}],
    )))
    for pid in ("base", "base__aaaaaaaaaaaa", "base__bbbbbbbbbbbb",
                "base__cccccccccccc", "unrelated"):
        _run(fake_stores["pipeline"].save(Pipeline(
            id=pid, name=pid, sources=["docs"], steps=_steps(),
            output_id=None, pipeline_type="eval",
        )))

    def _mkrun(pipeline_id, sweep_id, status="completed", f1=None):
        rid = _run(fake_stores["run"].create(pipeline_id))
        _run(fake_stores["run"].update(
            rid, status=status, eval_set_id="set1", sweep_id=sweep_id,
            scores={"macro_f1": f1} if f1 is not None else {},
        ))
        return rid

    # Sweep 1: two cells, both finished.
    _mkrun("base__aaaaaaaaaaaa", "sw1", f1=0.9)
    _mkrun("base__bbbbbbbbbbbb", "sw1", f1=0.7)
    # Sweep 2: launched later from a variant; one cell still running.
    _mkrun("base__cccccccccccc", "sw2", status="running")
    # A plain trigger — not part of any comparison.
    _mkrun("base", None)
    # Someone else's sweep entirely.
    _mkrun("unrelated", "sw3")
    return c


class TestListing:
    def test_lists_comparisons_for_the_pipeline(self, client):
        r = client.get("/api/pipelines/base/comparisons")
        assert r.status_code == 200, r.text
        assert {c["sweep_id"] for c in r.json()["comparisons"]} == {"sw1", "sw2"}

    def test_finds_sweeps_whose_runs_are_filed_under_cells(self, client):
        # The whole difficulty: no run of sw1 has pipeline_id == "base".
        ids = {c["sweep_id"] for c in client.get("/api/pipelines/base/comparisons").json()["comparisons"]}
        assert "sw1" in ids

    def test_excludes_another_pipelines_sweep(self, client):
        ids = {c["sweep_id"] for c in client.get("/api/pipelines/base/comparisons").json()["comparisons"]}
        assert "sw3" not in ids

    def test_excludes_plain_runs(self, client):
        # A trigger is not a comparison; listing it would put a row on the
        # page that opens an empty grid.
        rows = client.get("/api/pipelines/base/comparisons").json()["comparisons"]
        assert all(c["sweep_id"] for c in rows)

    def test_counts_cells(self, client):
        rows = {c["sweep_id"]: c for c in client.get("/api/pipelines/base/comparisons").json()["comparisons"]}
        assert rows["sw1"]["cells"] == 2
        assert rows["sw2"]["cells"] == 1

    def test_reports_how_many_are_still_running(self, client):
        rows = {c["sweep_id"]: c for c in client.get("/api/pipelines/base/comparisons").json()["comparisons"]}
        assert rows["sw1"]["pending"] == 0
        assert rows["sw2"]["pending"] == 1

    def test_carries_the_best_score_when_scored(self, client):
        rows = {c["sweep_id"]: c for c in client.get("/api/pipelines/base/comparisons").json()["comparisons"]}
        assert rows["sw1"]["best_macro_f1"] == 0.9

    def test_best_score_is_null_not_zero_when_unscored(self, client):
        # An unlabelled comparison is the normal case in this flow. Zero
        # would read as "every config failed".
        rows = {c["sweep_id"]: c for c in client.get("/api/pipelines/base/comparisons").json()["comparisons"]}
        assert rows["sw2"]["best_macro_f1"] is None

    def test_carries_the_eval_set(self, client):
        rows = client.get("/api/pipelines/base/comparisons").json()["comparisons"]
        assert all(c["eval_set_id"] == "set1" for c in rows)

    def test_newest_first(self, client):
        rows = client.get("/api/pipelines/base/comparisons").json()["comparisons"]
        assert [c["sweep_id"] for c in rows] == ["sw2", "sw1"]


class TestVariantRouting:
    def test_asking_from_a_variant_returns_the_roots_comparisons(self, client):
        # Someone landing on a cell must see the same history as the root,
        # not an empty page suggesting nothing was ever compared.
        rows = client.get("/api/pipelines/base__aaaaaaaaaaaa/comparisons").json()
        assert {c["sweep_id"] for c in rows["comparisons"]} == {"sw1", "sw2"}

    def test_reports_the_root_it_resolved_to(self, client):
        body = client.get("/api/pipelines/base__aaaaaaaaaaaa/comparisons").json()
        assert body["pipeline_id"] == "base"


class TestRejections:
    def test_unknown_pipeline_404s(self, client):
        assert client.get("/api/pipelines/nope/comparisons").status_code == 404

    def test_a_pipeline_with_no_comparisons_returns_an_empty_list(
        self, client, fake_stores
    ):
        # Empty, not 404 — "never compared" is an ordinary state, and the
        # panel needs something to render its empty copy from.
        _run(fake_stores["pipeline"].save(Pipeline(
            id="fresh", name="fresh", sources=["docs"], steps=_steps(),
            output_id=None, pipeline_type="eval",
        )))
        r = client.get("/api/pipelines/fresh/comparisons")
        assert r.status_code == 200
        assert r.json()["comparisons"] == []
