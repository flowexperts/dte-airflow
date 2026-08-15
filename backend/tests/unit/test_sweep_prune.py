"""A matrix is a product; a comparison is a set of distinct configs.

Reported: a provider × model sweep showed haiku and sonnet twice each.
The matrix was `provider: [claude, regex] × params.model: [haiku, sonnet]`,
expanded blindly to four cells — two of which set a model on `regex`, a
provider that never reads one. Those two are the *same config*, run twice,
billed as two columns labelled with models they do not use.

That is the failure the unknown-axis guard was built to prevent — N cells
that score identically, reading as "this setting makes no difference" —
arriving through a different door. The guard checks that an axis exists on
the step; it cannot know that a value on one axis makes another irrelevant.

So cells are pruned after expansion:

**Overrides the resolved provider ignores are stripped, then duplicates
collapse.** `regex × {haiku, sonnet}` is one regex cell, not two. This is
what the user meant by ticking regex alongside two models: compare regex
*against* them, not twice with each.

**A model that belongs to a different provider drops the cell.** `claude`
with `gpt-5` cannot run. Silently rewriting it to claude's default would
report a number under a config nobody chose.

Nothing is dropped silently — the estimate reports what was removed and why.
"""
from __future__ import annotations

import pytest

from dte.evals.sweep import prune_cells


class _Pipeline:
    def __init__(self, provider="regex"):
        self.id = "p"
        self.name = "p"
        self.steps = [
            {"op": "structure", "provider": provider, "params": {},
             "model": {"instructions": "",
                       "fields": [{"name": "t", "type": "float", "pattern": r"(\d+)"}]}},
        ]

    def model_dump(self):
        return {"id": self.id, "name": self.name, "steps": self.steps}


def _cells(kept):
    return [dict(c) for c in kept]


class TestRegexIgnoresModelSettings:
    def test_regex_with_two_models_collapses_to_one_cell(self):
        # The report: haiku and sonnet each appearing twice.
        kept, dropped = prune_cells(_Pipeline(), [
            {"provider": "claude", "params.model": "claude-haiku-4-5"},
            {"provider": "claude", "params.model": "claude-sonnet-5"},
            {"provider": "regex", "params.model": "claude-haiku-4-5"},
            {"provider": "regex", "params.model": "claude-sonnet-5"},
        ])
        assert len(kept) == 3
        assert {"provider": "regex"} in _cells(kept)
        assert len(dropped) == 1

    def test_the_surviving_regex_cell_carries_no_model(self):
        kept, _ = prune_cells(_Pipeline(), [
            {"provider": "regex", "params.model": "claude-haiku-4-5"},
        ])
        # Labelling a regex column "claude-haiku-4-5" claims it used a model.
        assert kept == [{"provider": "regex"}]

    def test_regex_ignores_instructions_too(self):
        # Three prompts against a provider that reads none is three
        # identical cells — exactly the conclusion-from-nothing the guard
        # exists to stop.
        kept, dropped = prune_cells(_Pipeline(), [
            {"provider": "regex", "model.instructions": "a"},
            {"provider": "regex", "model.instructions": "b"},
        ])
        assert kept == [{"provider": "regex"}]
        assert len(dropped) == 1

    def test_the_pipelines_own_provider_is_used_when_unswept(self):
        # No `provider` axis: the resolved provider is the step's own.
        kept, _ = prune_cells(_Pipeline(provider="regex"), [
            {"params.model": "claude-haiku-4-5"},
            {"params.model": "claude-sonnet-5"},
        ])
        assert len(kept) == 1

    def test_a_model_provider_keeps_its_model_axis(self):
        kept, dropped = prune_cells(_Pipeline(provider="claude"), [
            {"params.model": "claude-haiku-4-5"},
            {"params.model": "claude-sonnet-5"},
        ])
        assert len(kept) == 2
        assert dropped == []


class TestMismatchedModels:
    def test_claude_with_an_openai_model_is_dropped(self):
        kept, dropped = prune_cells(_Pipeline(), [
            {"provider": "claude", "params.model": "gpt-5"},
            {"provider": "claude", "params.model": "claude-haiku-4-5"},
        ])
        assert _cells(kept) == [{"provider": "claude", "params.model": "claude-haiku-4-5"}]
        assert len(dropped) == 1
        assert "gpt-5" in dropped[0]["reason"]

    def test_openai_with_a_claude_model_is_dropped(self):
        kept, dropped = prune_cells(_Pipeline(), [
            {"provider": "openai", "params.model": "claude-opus-5"},
        ])
        assert kept == []
        assert len(dropped) == 1

    def test_an_unknown_model_is_left_alone(self):
        # A model shipped after this table was written must not be refused
        # — the provider will say so far more accurately than a prefix.
        kept, dropped = prune_cells(_Pipeline(), [
            {"provider": "claude", "params.model": "claude-next-9"},
            {"provider": "openai", "params.model": "o5-preview"},
        ])
        assert len(kept) == 2
        assert dropped == []


class TestReporting:
    def test_dropped_cells_carry_the_cell_and_a_reason(self):
        _, dropped = prune_cells(_Pipeline(), [
            {"provider": "regex", "params.model": "claude-haiku-4-5"},
            {"provider": "regex", "params.model": "claude-sonnet-5"},
        ])
        assert dropped[0]["cell"] == {"provider": "regex", "params.model": "claude-sonnet-5"}
        assert "regex" in dropped[0]["reason"]

    def test_order_is_preserved(self):
        # Columns should sit in the order the matrix declared them.
        kept, _ = prune_cells(_Pipeline(), [
            {"provider": "claude", "params.model": "claude-sonnet-5"},
            {"provider": "claude", "params.model": "claude-haiku-4-5"},
        ])
        assert [c["params.model"] for c in kept] == ["claude-sonnet-5", "claude-haiku-4-5"]

    def test_an_empty_matrix_stays_empty(self):
        assert prune_cells(_Pipeline(), []) == ([], [])

    def test_a_single_plain_cell_is_untouched(self):
        kept, dropped = prune_cells(_Pipeline(), [{"provider": "claude"}])
        assert kept == [{"provider": "claude"}]
        assert dropped == []
