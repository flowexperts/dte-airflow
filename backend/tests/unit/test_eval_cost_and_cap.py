"""Two settings that read as configured and were not (plan 053).

Both are the same class of bug: something *looks* like it works. The cost
table returns "unknown" rather than a wrong number, so an OpenAI sweep
silently reports no cost at all — and the flow's headline question is
"which provider is worth the money". The sweep cap names an env var in its
own error message that has never been read.

Neither raises. Both are only visible if you go looking, which is why they
get tests.
"""
from __future__ import annotations

import pytest

from dte.config import Settings
from dte.evals.cost import PRICES, estimate_cost


class TestOpenAIPricing:
    """An unpriced model nulls the total for the whole run by design —
    a partial sum is a wrong bill that errs low. Correct, and useless the
    moment openai is one of the columns being compared."""

    @pytest.mark.parametrize("model", ["gpt-5", "gpt-5-mini"])
    def test_openai_models_are_priced(self, model):
        assert model in PRICES

    def test_an_openai_run_reports_a_number(self, model="gpt-5"):
        assert estimate_cost(model, 1_000_000, 1_000_000) is not None

    def test_claude_pricing_is_unchanged(self):
        assert PRICES["claude-opus-5"] == (5.00, 25.00)
        assert PRICES["claude-haiku-4-5"] == (1.00, 5.00)

    def test_an_unknown_model_is_still_none_not_a_guess(self):
        # The rule this module was built on stays: a fabricated dollar
        # figure gets budgeted against and is wrong in a direction nobody
        # can see. Adding prices must not turn that into a fallback.
        assert estimate_cost("some-model-shipped-next-year", 1000, 1000) is None

    def test_deterministic_providers_still_cost_nothing(self):
        assert estimate_cost("regex", 10_000, 10_000) == 0.0


class TestSweepCap:
    def test_the_cap_is_a_real_setting(self):
        # It was read with getattr off a Settings that has no such field and
        # `extra="ignore"`, so DTE_EVAL_MAX_SWEEP_CELLS — named in the error
        # message telling users to raise it — did nothing.
        assert Settings().eval_max_sweep_cells == 50

    def test_the_cap_is_overridable_by_env(self, monkeypatch):
        monkeypatch.setenv("DTE_EVAL_MAX_SWEEP_CELLS", "8")
        assert Settings().eval_max_sweep_cells == 8
