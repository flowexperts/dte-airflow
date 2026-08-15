"""A sweep may introduce a key the base config never had (plan 053).

`apply_cell` refused to *create* a leaf, only to overwrite one. The guard
was aimed at the right target — a typo'd axis silently becoming N identical
cells reads as "this setting makes no difference", which is worse than an
error — but it was too broad, and it broke the flow's most ordinary case:

    Compare the regex config you already have against claude.

A regex structure step has `params: {}`, because regex makes no model
calls. Sweeping `provider: [regex, claude]` also needs `params.model` for
the claude cell, and that key does not exist on the base step. The sweep
422'd with "no 'model' under 'params'" — naming a key the user never typed,
on a pipeline that is perfectly valid.

The fix keeps the guard and narrows it: a known axis may be created, an
unknown one still raises. A typo is not on the allowlist, so the failure it
was built to prevent still fails.
"""
from __future__ import annotations

import pytest

from dte.evals.sweep import apply_cell


class _Pipeline:
    """Minimal stand-in — `apply_cell` only needs `steps` and `model_dump`."""

    def __init__(self, steps):
        self.id = "p"
        self.steps = steps

    def model_dump(self):
        return {"steps": self.steps}


def _regex_pipeline():
    return _Pipeline([
        {"op": "extract", "provider": "pdfplumber", "params": {}},
        {"op": "structure", "input_field": "content", "provider": "regex",
         "on_error": "null", "params": {},
         "model": {"fields": [{"name": "total", "type": "float", "pattern": r"(\d+)"}]}},
    ])


class TestKnownAxesMayBeCreated:
    def test_params_model_can_be_introduced(self):
        # The exact failure: "unknown sweep axis 'params.model': no 'model'
        # under 'params'" when comparing a regex config against a model.
        variant = apply_cell(_regex_pipeline(), {"params.model": "claude-opus-5"})
        assert variant.steps[1]["params"]["model"] == "claude-opus-5"

    def test_model_instructions_can_be_introduced(self):
        # A structure step saved before instructions existed, or simply one
        # the user never wrote instructions on.
        p = _Pipeline([
            {"op": "structure", "provider": "claude", "params": {},
             "model": {"fields": [{"name": "total", "type": "float"}]}},
        ])
        variant = apply_cell(p, {"model.instructions": "ignore the stub"})
        assert variant.steps[0]["model"]["instructions"] == "ignore the stub"

    def test_params_max_tokens_can_be_introduced(self):
        variant = apply_cell(_regex_pipeline(), {"params.max_tokens": 8192})
        assert variant.steps[1]["params"]["max_tokens"] == 8192

    def test_provider_and_model_vary_together(self):
        # One cell of the comparison this whole plan exists to enable.
        variant = apply_cell(
            _regex_pipeline(), {"provider": "claude", "params.model": "claude-opus-5"}
        )
        step = variant.steps[1]
        assert step["provider"] == "claude"
        assert step["params"]["model"] == "claude-opus-5"

    def test_the_base_pipeline_is_not_mutated(self):
        base = _regex_pipeline()
        apply_cell(base, {"params.model": "claude-opus-5"})
        assert base.steps[1]["params"] == {}


class TestTheGuardStillGuards:
    def test_a_typo_under_params_still_raises(self):
        # The reason the guard exists. `params.modle` would otherwise be
        # created happily, and every cell would score identically — reading
        # as "the model makes no difference here".
        with pytest.raises(ValueError, match="modle"):
            apply_cell(_regex_pipeline(), {"params.modle": "claude-opus-5"})

    def test_a_typo_under_model_still_raises(self):
        with pytest.raises(ValueError, match="instrucions"):
            apply_cell(_regex_pipeline(), {"model.instrucions": "x"})

    def test_an_unknown_top_level_axis_still_raises(self):
        with pytest.raises(ValueError, match="temperture"):
            apply_cell(_regex_pipeline(), {"temperture": 0.5})

    def test_an_unknown_parent_still_raises(self):
        # Not on the allowlist and no such parent — nothing to attach to.
        with pytest.raises(ValueError, match="retries"):
            apply_cell(_regex_pipeline(), {"retries.count": 3})

    def test_a_non_dict_parent_still_raises(self):
        p = _Pipeline([
            {"op": "structure", "provider": "claude", "params": {},
             "model": {"fields": [{"name": "t", "type": "float"}]}},
        ])
        # `provider` is a string; nothing can live under it.
        with pytest.raises(ValueError, match="not a nested object"):
            apply_cell(p, {"provider.name": "claude"})

    def test_still_raises_with_no_structure_step(self):
        with pytest.raises(ValueError, match="no structure step"):
            apply_cell(_Pipeline([{"op": "extract", "params": {}}]), {"provider": "claude"})
