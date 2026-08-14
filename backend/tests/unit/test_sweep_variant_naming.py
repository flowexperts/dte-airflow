"""Sweep variants namespace under the config you authored (plan 053).

Sweep cells become real pipelines — deliberately, so a winner can be
promoted and a run has something to point at. But they also appear in
Pipelines → Eval carrying their own Compare button, and comparing a variant
nested it under itself:

    demo_eval_strict
    demo_eval_strict__27fb9c1d2679
    demo_eval_strict__27fb9c1d2679__27fb9c1d2679
    demo_eval_strict__27fb9c1d2679__27fb9c1d2679__37f7b8bbec71

with names accumulating to match: "demo eval strict · instructions=v3 ·
provider=regex · provider=claude, model=claude-haiku-4-5".

Two harms, and the second is the one that matters. The ids are unreadable —
annoying. But the *config* also accumulates: that last sweep varied
`provider` on a pipeline whose provider a previous cell had already pinned,
so one cell was identical to its own base and the user was comparing
against something they never chose.

A variant is an artifact of a comparison, not a config anyone authored. So
it namespaces under the root, and its name describes the root plus its own
overrides — never a chain.
"""
from __future__ import annotations

import pytest

from dte.evals.sweep import root_pipeline_id, variant_id, variant_name


_DEFAULT_STEPS = [
    {"op": "structure", "provider": "regex", "params": {},
     "model": {"instructions": "", "fields": [{"name": "t", "type": "float"}]}},
]


class _Pipeline:
    """Round-trips through `detached_copy`, which rebuilds via
    `type(pipeline)(**model_dump())` — so every field must come back."""

    def __init__(self, id="p", name="p", steps=None):
        self.id = id
        self.name = name
        self.steps = steps if steps is not None else [dict(s) for s in _DEFAULT_STEPS]

    def model_dump(self):
        return {"id": self.id, "name": self.name, "steps": self.steps}


class TestRootPipelineId:
    def test_a_plain_id_is_its_own_root(self):
        assert root_pipeline_id("demo_eval_strict") == "demo_eval_strict"

    def test_one_variant_suffix_is_stripped(self):
        assert root_pipeline_id("demo_eval_strict__27fb9c1d2679") == "demo_eval_strict"

    def test_every_variant_suffix_is_stripped(self):
        assert root_pipeline_id(
            "demo_eval_strict__27fb9c1d2679__27fb9c1d2679__37f7b8bbec71"
        ) == "demo_eval_strict"

    def test_the_eval_twin_suffix_is_kept(self):
        # `__eval` is a twin, not a sweep cell. It is the pipeline someone
        # compares *from*, so collapsing it would send variants to the
        # transform pipeline and break the corpus-match rule.
        assert root_pipeline_id("invoices__eval") == "invoices__eval"

    def test_a_twin_that_was_swept_collapses_to_the_twin(self):
        assert root_pipeline_id("invoices__eval__27fb9c1d2679") == "invoices__eval"

    @pytest.mark.parametrize("pid", [
        "orders__2024",           # not hex
        "orders__abc",            # too short
        "orders__27fb9c1d267",    # 11 chars
        "orders__27fb9c1d26799",  # 13 chars
        "orders__27FB9C1D2679",   # uppercase — digests are lowercase
    ])
    def test_a_lookalike_suffix_is_not_stripped(self, pid):
        # A user's own id ending in something digest-shaped must survive.
        # Stripping it would file their sweeps under a pipeline that does
        # not exist.
        assert root_pipeline_id(pid) == pid


class TestVariantId:
    def test_a_variant_of_the_root_is_namespaced_under_it(self):
        vid = variant_id(_Pipeline("demo_eval_strict", "demo"), {"provider": "claude"})
        assert vid.startswith("demo_eval_strict__")
        assert vid.count("__") == 1

    def test_a_variant_of_a_variant_does_not_nest(self):
        # The reported bug.
        base = _Pipeline("demo_eval_strict__27fb9c1d2679", "demo · instructions=v3")
        vid = variant_id(base, {"provider": "claude"})
        assert vid.count("__") == 1
        assert vid.startswith("demo_eval_strict__")

    def test_the_digest_still_reflects_the_full_resolved_config(self):
        # Rooting the *namespace* must not root the config. A variant of a
        # variant inherits the parent's overrides, and its id has to differ
        # from the same cell applied to the root — otherwise two different
        # configs collide on one id and one silently overwrites the other.
        root = _Pipeline("p", "p")
        child = _Pipeline("p__aaaaaaaaaaaa", "p · x", steps=[
            {"op": "structure", "provider": "regex", "params": {},
             "model": {"instructions": "already varied",
                       "fields": [{"name": "t", "type": "float"}]}},
        ])
        assert variant_id(root, {"provider": "claude"}) != variant_id(
            child, {"provider": "claude"})

    def test_the_same_cell_on_the_same_base_is_stable(self):
        # Re-running a sweep must land on the same row and hit the cache.
        base = _Pipeline("p", "p")
        assert variant_id(base, {"provider": "claude"}) == variant_id(
            base, {"provider": "claude"})


class TestVariantName:
    def test_a_variant_of_the_root_names_the_root_and_its_cell(self):
        assert variant_name(
            _Pipeline("p", "demo eval strict"), {"provider": "claude"}
        ) == "demo eval strict · provider=claude"

    def test_a_variant_of_a_variant_does_not_accumulate(self):
        # Was: "demo eval strict · instructions=v3 · provider=regex ·
        #       provider=claude, model=claude-haiku-4-5"
        assert variant_name(
            _Pipeline("p__27fb9c1d2679", "demo eval strict · instructions=v3"),
            {"provider": "claude"},
        ) == "demo eval strict · provider=claude"

    def test_multiple_axes_are_joined(self):
        assert variant_name(
            _Pipeline("p", "demo"),
            {"provider": "claude", "params.model": "claude-haiku-4-5"},
        ) == "demo · provider=claude, model=claude-haiku-4-5"

    def test_a_name_with_a_middot_of_its_own_survives(self):
        # Only the suffix this module added is removed, and only when the id
        # says the pipeline is a variant.
        assert variant_name(
            _Pipeline("p", "orders · EU"), {"provider": "claude"}
        ) == "orders · EU · provider=claude"
