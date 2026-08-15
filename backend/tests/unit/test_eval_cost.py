"""Cost and throughput accounting for eval runs (plan 051).

The plan's economic argument is that caching makes sweeps affordable. That
argument is unfalsifiable until the numbers are on screen, so a run records
what it spent, how much of it was cached, and how slow it was.

The one rule that shapes everything here: **an unknown price is null, never
a guess.** A fabricated dollar figure is worse than no figure — people
budget against it, and it is wrong in a direction nobody can see. Tokens
are always reported, because they are measured; dollars only when the model
is in the price table.
"""
from __future__ import annotations

import pytest

from dte.evals.cost import PRICES, estimate_cost, throughput_stats


def test_a_known_model_prices_from_the_table():
    # claude-opus-5: $5/1M in, $25/1M out.
    cost = estimate_cost("claude-opus-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(30.0)


def test_an_unknown_model_yields_null_not_a_guess():
    """A made-up price is worse than a missing one: it gets budgeted
    against, and it is wrong in a direction nobody can inspect."""
    assert estimate_cost("some-new-model-9", 1_000_000, 1_000_000) is None


def test_zero_tokens_on_a_known_model_is_zero_not_null():
    """A fully-cached run genuinely cost nothing. Reporting null there would
    hide the single most important fact about the cache."""
    assert estimate_cost("claude-opus-5", 0, 0) == 0.0


def test_every_priced_model_has_both_rates():
    for model, rates in PRICES.items():
        assert len(rates) == 2, model
        assert all(r >= 0 for r in rates), model


def _row(*, ms, cached, in_tok=0, out_tok=0, model="claude-opus-5"):
    import json
    return {
        "structure_meta": json.dumps({
            "provider": "claude", "cached": cached, "ms": ms,
            "input_tokens": in_tok, "output_tokens": out_tok, "model": model,
        })
    }


def test_cache_hit_rate_counts_rows_that_made_no_call():
    stats = throughput_stats([
        _row(ms=0, cached=True),
        _row(ms=800, cached=False, in_tok=1000, out_tok=100),
        _row(ms=900, cached=False, in_tok=1000, out_tok=100),
        _row(ms=0, cached=True),
    ])
    assert stats["cache_hit_rate"] == pytest.approx(0.5)
    assert stats["n_calls"] == 2


def test_latency_percentiles_ignore_cached_rows():
    """A cache hit is not a fast model call, it is the absence of one.
    Averaging its 0ms into the latency makes a slow provider look fast in
    exact proportion to how often you re-run it."""
    stats = throughput_stats([
        _row(ms=0, cached=True),
        _row(ms=1000, cached=False),
        _row(ms=1000, cached=False),
    ])
    assert stats["latency_p50_ms"] == 1000
    assert stats["latency_p95_ms"] == 1000


def test_cost_sums_tokens_across_rows():
    stats = throughput_stats([
        _row(ms=10, cached=False, in_tok=500_000, out_tok=0),
        _row(ms=10, cached=False, in_tok=500_000, out_tok=0),
    ])
    assert stats["input_tokens"] == 1_000_000
    assert stats["cost_usd"] == pytest.approx(5.0)


def test_a_run_with_no_structure_step_reports_nulls_not_zeros():
    """A transform that never called a model has no latency and no cost.
    Zero would read as 'instant and free', which is a claim about a model
    call that never happened."""
    stats = throughput_stats([{"total": "1"}, {"total": "2"}])
    assert stats["n_calls"] == 0
    assert stats["cost_usd"] is None
    assert stats["latency_p50_ms"] is None
    assert stats["cache_hit_rate"] is None


def test_mixed_models_price_per_row(monkeypatch):
    """Rows can come from different models when a sweep is in flight; each
    row prices against the model that actually served it."""
    stats = throughput_stats([
        _row(ms=10, cached=False, in_tok=1_000_000, out_tok=0, model="claude-opus-5"),
        _row(ms=10, cached=False, in_tok=1_000_000, out_tok=0, model="claude-haiku-4-5"),
    ])
    # $5 + $1
    assert stats["cost_usd"] == pytest.approx(6.0)


def test_one_unpriced_model_makes_the_total_null():
    """A partial total is a wrong total. If any row cannot be priced, the
    sum understates the true spend, and an understated bill is the failure
    mode that actually hurts."""
    stats = throughput_stats([
        _row(ms=10, cached=False, in_tok=1_000_000, out_tok=0, model="claude-opus-5"),
        _row(ms=10, cached=False, in_tok=1_000_000, out_tok=0, model="mystery-model"),
    ])
    assert stats["cost_usd"] is None
    # Tokens are measured, so they are still reported.
    assert stats["input_tokens"] == 2_000_000
