"""The `llm_judge` comparator (plan 051).

For free-text fields — a summary, a reason, a description — exact match is
meaningless: two correct answers rarely share a wording. A judge is the
only way to score them, and it carries two hazards the rest of the module
does not.

**It costs money and it is non-deterministic**, while the plan's most
load-bearing assertion is that re-scoring a cached run reproduces the same
number. So every verdict is cached on `(expected, actual, judge_config)`.
Without that, re-opening a leaderboard could quietly change history.

**It is never a default.** A judge sharing a model family with the
extractor will flatter it, so it has to be asked for by name, and the UI
marks fields scored this way.
"""
from __future__ import annotations

import pytest

from dte.evals.comparators import COMPARATOR_TYPES, compare
from dte.evals.judge import JudgeUnavailable, clear_judge_cache, set_judge


@pytest.fixture(autouse=True)
def _clean():
    clear_judge_cache()
    set_judge(None)
    yield
    clear_judge_cache()
    set_judge(None)


def test_llm_judge_is_a_declarable_comparator_type():
    assert "llm_judge" in COMPARATOR_TYPES


def test_without_a_configured_judge_it_refuses_rather_than_guessing():
    """No judge must never silently degrade to string equality. A field
    declared as free-text would then score near zero and read as a broken
    extractor rather than a missing configuration."""
    with pytest.raises(JudgeUnavailable):
        compare("the invoice was disputed", "customer disputed the invoice", "llm_judge")


def test_the_judge_verdict_is_returned():
    set_judge(lambda expected, actual, opts: (True, "same meaning"))
    r = compare("the invoice was disputed", "customer disputed the invoice", "llm_judge")
    assert r.matched is True
    assert r.score == 1.0
    assert "same meaning" in r.reason


def test_a_negative_verdict_is_a_mismatch_not_an_error():
    set_judge(lambda expected, actual, opts: (False, "different claims"))
    r = compare("shipped on time", "shipment was late", "llm_judge")
    assert r.matched is False
    assert r.score == 0.0


def test_identical_strings_never_reach_the_judge():
    """Paying a model to confirm that a string equals itself is waste, and
    on a large corpus it is most of the bill."""
    calls = []

    def judge(expected, actual, opts):
        calls.append((expected, actual))
        return (False, "should not have been asked")

    set_judge(judge)
    r = compare("identical text", "identical text", "llm_judge")
    assert r.matched is True
    assert calls == []


def test_the_same_pair_is_judged_once_and_then_cached():
    """Determinism is the harness's load-bearing property: re-scoring a run
    must reproduce its number exactly. An uncached judge would let a
    leaderboard change when nothing changed."""
    calls = []

    def judge(expected, actual, opts):
        calls.append((expected, actual))
        return (True, "equivalent")

    set_judge(judge)
    first = compare("a long free text answer", "a differently worded answer", "llm_judge")
    second = compare("a long free text answer", "a differently worded answer", "llm_judge")
    assert len(calls) == 1
    assert first.matched == second.matched


def test_changing_the_judge_config_re_judges():
    """The cache key includes the options, so tightening the rubric is not
    silently ignored in favour of a verdict reached under the old one."""
    calls = []

    def judge(expected, actual, opts):
        calls.append(opts.get("rubric"))
        return (True, "ok")

    set_judge(judge)
    compare("x text", "y text", "llm_judge", {"rubric": "lenient"})
    compare("x text", "y text", "llm_judge", {"rubric": "strict"})
    assert calls == ["lenient", "strict"]
