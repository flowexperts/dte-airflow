"""Best score and last run on the eval-set list (plan 051 phase 4).

The list previously said a set existed and nothing about how it was doing,
so the only way to learn that a corpus had never been run — or had been
scoring badly for a week — was to open it. A list of eval sets whose
scores are invisible is a list nobody checks.

The stale rule from the leaderboard applies here too: a best score drawn
from a run scored against superseded labels is not this set's current best,
and showing it would put a number on the index page that the detail page
contradicts.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app
from dte.models.eval import EvalSetBase


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def client(fake_stores):
    c = TestClient(app)
    _run(fake_stores["eval_set"].save(EvalSetBase(
        id="ls_set", name="Invoices", source_id="s",
        field_specs=[{"name": "total", "type": "numeric"}],
    )))
    yield c, fake_stores


def _seed_run(stores, *, macro_f1, labels_version, status="completed"):
    rid = _run(stores["run"].create("p"))
    _run(stores["run"].update(
        rid, status=status, eval_set_id="ls_set", labels_version=labels_version,
        scores={"macro_f1": macro_f1, "n": 4},
    ))
    return rid


def _row(c):
    rows = c.get("/api/eval-sets").json()
    return next(r for r in rows if r["id"] == "ls_set")


def test_a_set_that_has_never_run_reports_no_score(client):
    """Null, not zero. An unmeasured set and a set scoring zero are opposite
    situations and must not render identically."""
    c, _ = client
    row = _row(c)
    assert row["best_macro_f1"] is None
    assert row["last_run_at"] is None


def test_the_best_non_stale_score_is_reported(client):
    c, stores = client
    _seed_run(stores, macro_f1=0.62, labels_version=1)
    _seed_run(stores, macro_f1=0.91, labels_version=1)
    row = _row(c)
    assert row["best_macro_f1"] == pytest.approx(0.91)
    assert row["last_run_at"] is not None


def test_runs_scored_against_older_labels_do_not_set_the_best(client):
    """A 0.99 earned against labels that have since been corrected is not
    this set's best. Reporting it puts a number on the list page that the
    leaderboard — which greys that run out — directly contradicts."""
    c, stores = client
    _run(stores["eval_set"].bump_labels_version("ls_set"))  # -> v2
    _seed_run(stores, macro_f1=0.99, labels_version=1)      # stale
    _seed_run(stores, macro_f1=0.55, labels_version=2)      # current
    row = _row(c)
    assert row["best_macro_f1"] == pytest.approx(0.55)


def test_a_failed_run_contributes_no_score_but_still_counts_as_activity(client):
    c, stores = client
    _seed_run(stores, macro_f1=None, labels_version=1, status="failed")
    row = _row(c)
    assert row["best_macro_f1"] is None
    # It still ran — "last activity" is about whether anyone is using this
    # set, not about whether the run succeeded.
    assert row["last_run_at"] is not None
