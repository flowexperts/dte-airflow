"""Sweep cell expansion into real pipeline variants (plan 051 phase 4).

The sweep endpoint used to return `enqueued: true` alongside a list of
cells and start nothing. That is the worst possible shape for this feature:
a launcher that reports success, charges nothing, produces no runs, and
leaves an empty leaderboard that looks like the configs all failed.

A cell is only meaningful if it becomes a pipeline whose `config_digest`
differs from its siblings — the digest is what the leaderboard groups by,
so two cells that collapse to the same digest are one config that will
overwrite itself and report as a single row.
"""
from __future__ import annotations

import pytest

from dte.evals.digest import config_digest
from dte.evals.sweep import apply_cell, variant_id
from dte.models.pipeline import Pipeline, PipelineBase


def _pipeline(pid="sw_base"):
    return Pipeline(**PipelineBase(
        id=pid, name=pid, sources=["s"], output_id=None, pipeline_type="eval",
        steps=[
            {"op": "extract", "source_field": "path", "provider": "pdfplumber",
             "granularity": "page", "output_field": "content", "params": {}},
            {"op": "structure", "input_field": "content", "provider": "regex",
             "on_error": "null", "params": {"max_pages": 1},
             "model": {"instructions": "base", "fields": [
                 {"name": "total", "type": "string", "required": False,
                  "description": "d", "pattern": "x"}]}},
        ],
    ).model_dump())


def _structure(p):
    return next(s for s in p.steps if s["op"] == "structure")


def test_a_top_level_axis_overrides_the_structure_step():
    out = apply_cell(_pipeline(), {"provider": "claude"})
    assert _structure(out)["provider"] == "claude"


def test_a_dotted_axis_reaches_into_nested_config():
    out = apply_cell(_pipeline(), {"params.max_pages": 3, "model.instructions": "v2"})
    s = _structure(out)
    assert s["params"]["max_pages"] == 3
    assert s["model"]["instructions"] == "v2"


def test_the_base_pipeline_is_not_mutated():
    """Cells are generated in a loop off one base. Mutating it in place would
    make every cell inherit the previous cell's overrides — a sweep that
    silently measures a diagonal instead of a grid."""
    base = _pipeline()
    apply_cell(base, {"provider": "claude"})
    assert _structure(base)["provider"] == "regex"


def test_distinct_cells_produce_distinct_digests():
    base = _pipeline()
    a = config_digest(apply_cell(base, {"provider": "claude"}))
    b = config_digest(apply_cell(base, {"provider": "openai"}))
    assert a != b


def test_the_same_cell_is_stable_across_calls():
    """Re-running a sweep must land on the same digest and the same variant
    id, or the extract/structure cache is bypassed and the re-run is paid
    for twice while reporting as a different config."""
    base = _pipeline()
    cell = {"provider": "claude", "params.max_pages": 3}
    assert config_digest(apply_cell(base, cell)) == config_digest(apply_cell(base, cell))
    assert variant_id(base, cell) == variant_id(base, cell)


def test_variant_id_is_derived_and_namespaced_under_the_base():
    base = _pipeline()
    vid = variant_id(base, {"provider": "claude"})
    assert vid.startswith("sw_base__")
    assert vid != variant_id(base, {"provider": "openai"})


def test_a_pipeline_with_no_structure_step_is_rejected():
    p = Pipeline(**PipelineBase(
        id="nostruct", name="nostruct", sources=["s"], output_id="d", steps=[],
    ).model_dump())
    with pytest.raises(ValueError, match="structure"):
        apply_cell(p, {"provider": "claude"})


def test_an_unknown_axis_is_rejected_rather_than_silently_ignored():
    """A typo'd axis that is quietly dropped produces N identical cells,
    every one reporting the same score, and reads as 'the setting made no
    difference' — a conclusion drawn from a spelling mistake."""
    with pytest.raises(ValueError, match="nonsense"):
        apply_cell(_pipeline(), {"nonsense": "x"})


def test_the_variant_shares_no_step_objects_with_the_base():
    """Guards the bug that only appeared against Postgres.

    A pipeline loaded from the database is a live SQLAlchemy-instrumented
    instance; `copy.deepcopy` carries that instrumentation with it, and
    assigning to `.id` on the result raises `ObjectDereferencedError` once
    the original is collected. The fakes hand back detached instances, so
    the whole unit suite passed while a real sweep 500'd. Rebuilding from
    `model_dump()` is what makes the variant an ordinary object — this
    asserts the structural consequence.
    """
    base = _pipeline()
    variant = apply_cell(base, {"provider": "claude"})
    variant.id = "renamed"
    assert base.id == "sw_base"
    assert _structure(variant) is not _structure(base)
    assert _structure(base)["provider"] == "regex"
