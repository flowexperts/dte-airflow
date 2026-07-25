"""Unit tests for `dte.pipelines.diff`.

Snapshot-style asserts on the structured diff so any future format change
surfaces here — not in the frontend."""
from __future__ import annotations

from dte.pipelines.diff import diff_pipeline, summarise_diff


def _p(**overrides):
    base = {
        "id": "p1",
        "name": "orig",
        "sources": ["src_a"],
        "output_id": "dst_a",
        "steps": [
            {"op": "filter", "condition": "x > 1"},
            {"op": "rename", "mapping": {"a": "b"}},
        ],
    }
    base.update(overrides)
    return base


def test_no_changes_is_empty_diff():
    d = diff_pipeline(_p(), _p())
    assert d["name_changed"] is False
    assert d["sources_added"] == []
    assert d["sources_removed"] == []
    assert d["output_id_changed"] is False
    assert d["steps"] == []
    assert summarise_diff(d) == "no changes"


def test_name_change_only():
    d = diff_pipeline(_p(name="orig"), _p(name="renamed"))
    assert d["name_changed"] is True
    assert d["name_before"] == "orig"
    assert d["name_after"] == "renamed"
    assert d["steps"] == []
    assert "orig" in summarise_diff(d) and "renamed" in summarise_diff(d)


def test_added_step_at_end():
    after = _p(steps=[
        {"op": "filter", "condition": "x > 1"},
        {"op": "rename", "mapping": {"a": "b"}},
        {"op": "sort", "by": "b"},
    ])
    d = diff_pipeline(_p(), after)
    assert len(d["steps"]) == 1
    assert d["steps"][0] == {
        "index": 2, "kind": "added", "op": "sort",
        "before": None, "after": {"op": "sort", "by": "b"},
    }
    assert "+sort" in summarise_diff(d)


def test_removed_step_at_end():
    after = _p(steps=[{"op": "filter", "condition": "x > 1"}])
    d = diff_pipeline(_p(), after)
    assert len(d["steps"]) == 1
    assert d["steps"][0]["kind"] == "removed"
    assert d["steps"][0]["op"] == "rename"
    assert "-rename" in summarise_diff(d)


def test_changed_step_in_place():
    after = _p(steps=[
        {"op": "filter", "condition": "x > 2"},   # condition mutated
        {"op": "rename", "mapping": {"a": "b"}},
    ])
    d = diff_pipeline(_p(), after)
    assert len(d["steps"]) == 1
    assert d["steps"][0]["kind"] == "changed"
    assert d["steps"][0]["op"] == "filter"
    assert d["steps"][0]["before"]["condition"] == "x > 1"
    assert d["steps"][0]["after"]["condition"] == "x > 2"
    assert "~filter" in summarise_diff(d)


def test_sources_added_removed_and_output_change():
    after = _p(sources=["src_b", "src_c"], output_id="dst_new")
    d = diff_pipeline(_p(), after)
    assert d["sources_added"] == ["src_b", "src_c"]
    assert d["sources_removed"] == ["src_a"]
    assert d["output_id_changed"] is True
    s = summarise_diff(d)
    assert "sources:" in s and "output:" in s


def test_diff_is_deterministic_snapshot():
    # Locked shape so a schema change here forces a conscious update.
    d = diff_pipeline(
        {"id": "p", "name": "a", "sources": [], "output_id": "o", "steps": []},
        {"id": "p", "name": "b", "sources": ["x"], "output_id": "o", "steps": [
            {"op": "sort", "by": "x"},
        ]},
    )
    assert d == {
        "name_changed": True,
        "name_before": "a",
        "name_after": "b",
        "sources_added": ["x"],
        "sources_removed": [],
        "output_id_changed": False,
        "output_id_before": "o",
        "output_id_after": "o",
        "steps": [
            {"index": 0, "kind": "added", "op": "sort",
             "before": None, "after": {"op": "sort", "by": "x"}},
        ],
    }
