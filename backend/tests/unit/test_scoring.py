"""Scoring turns thousands of right/wrong verdicts into a number you can rank.

The cases that matter most are the ones distinguishing *correct abstention*
from a *silent miss* — the distinction that makes "accuracy" a lie.
"""

import pytest

from dte.evals.scoring import (
    FieldSpec,
    intervals_overlap,
    score_corpus,
    score_field,
    wilson_interval,
)


# ── the four-way classification ─────────────────────────────────────────────


def test_true_positive():
    m = score_field([(1240.50, "$1,240.50")], "numeric")
    assert (m.tp, m.fp, m.fn, m.tn) == (1, 0, 0, 0)


def test_wrong_answer_counts_against_both_precision_and_recall():
    """A wrong answer is two failures: you emitted something incorrect *and*
    you failed to produce the right value. Counting it only as a false
    positive would let an extractor that answers everything wrong report
    perfect recall."""
    m = score_field([(1240.50, "9999.00")], "numeric")
    assert (m.tp, m.fp, m.fn, m.tn) == (0, 1, 1, 0)


def test_silent_miss_is_a_false_negative():
    m = score_field([("Acme", None)], "string")
    assert (m.tp, m.fp, m.fn, m.tn) == (0, 0, 1, 0)


def test_hallucination_is_a_false_positive():
    m = score_field([(None, "Acme")], "string")
    assert (m.tp, m.fp, m.fn, m.tn) == (0, 1, 0, 0)


def test_correct_abstention_is_a_true_negative_and_leaves_precision_alone():
    """Both null means the extractor was right to say nothing. It must not
    inflate precision, and it must not count as a miss."""
    m = score_field([(None, None)], "string")
    assert (m.tp, m.fp, m.fn, m.tn) == (0, 0, 0, 1)
    assert m.precision is None      # nothing was answered — undefined, not 1.0
    assert m.recall is None         # nothing was expected — undefined, not 0.0


# ── the headline lie ────────────────────────────────────────────────────────


def test_abstaining_extractor_scores_low_recall_not_high_accuracy():
    """1 of 10 answered and correct, 9 abstentions. 'Accuracy over answered
    rows' would report 100%. Recall reports 0.1, which is the truth."""
    pairs = [("a", "a")] + [(f"v{i}", None) for i in range(9)]
    m = score_field(pairs, "string")

    assert m.tp == 1 and m.fn == 9 and m.fp == 0
    assert m.precision == pytest.approx(1.0)
    assert m.recall == pytest.approx(0.1)
    assert m.f1 == pytest.approx(2 * 1.0 * 0.1 / 1.1)
    assert m.null_rate == pytest.approx(0.9)


def test_answering_everything_wrong_does_not_report_perfect_recall():
    pairs = [(f"v{i}", "wrong") for i in range(10)]
    m = score_field(pairs, "string")
    assert m.recall == pytest.approx(0.0)
    assert m.precision == pytest.approx(0.0)


# ── derived metrics ─────────────────────────────────────────────────────────


def test_precision_recall_f1_arithmetic():
    # 6 correct, 2 wrong, 2 missed
    pairs = (
        [("x", "x")] * 6
        + [("x", "y")] * 2
        + [("x", None)] * 2
    )
    m = score_field(pairs, "string")
    assert (m.tp, m.fp, m.fn, m.tn) == (6, 2, 4, 0)
    assert m.precision == pytest.approx(6 / 8)
    assert m.recall == pytest.approx(6 / 10)
    assert m.f1 == pytest.approx(2 * 0.75 * 0.6 / 1.35)
    assert m.n == 10


def test_n_counts_documents_not_classifications():
    m = score_field([("x", "x"), ("y", None), (None, None)], "string")
    assert m.n == 3


def test_empty_input_yields_undefined_not_zero():
    m = score_field([], "string")
    assert m.n == 0
    assert m.precision is None and m.recall is None and m.f1 is None


# ── corpus level ────────────────────────────────────────────────────────────


def _specs():
    return [
        FieldSpec(name="invoice_total", type="numeric"),
        FieldSpec(name="vendor_name", type="string"),
    ]


def test_macro_f1_is_the_mean_of_per_field_f1():
    rows = [
        ({"invoice_total": 100.0, "vendor_name": "Acme"},
         {"invoice_total": "100.00", "vendor_name": "Acme"}),
        ({"invoice_total": 200.0, "vendor_name": "Globex"},
         {"invoice_total": "200.00", "vendor_name": "WRONG"}),
    ]
    score = score_corpus(rows, _specs())

    assert score.fields["invoice_total"].f1 == pytest.approx(1.0)
    assert score.fields["vendor_name"].f1 == pytest.approx(0.5)
    assert score.macro_f1 == pytest.approx(0.75)
    assert score.n == 2


def test_macro_f1_does_not_let_one_easy_field_carry_the_score():
    """Macro, not micro: a field with 100 easy rows must not drown out a
    field with 2 hard ones."""
    rows = [
        ({"invoice_total": 1.0, "vendor_name": "Acme"},
         {"invoice_total": "1", "vendor_name": "WRONG"})
    ] * 100
    score = score_corpus(rows, _specs())
    assert score.macro_f1 == pytest.approx(0.5)


def test_fields_absent_from_a_row_are_treated_as_null():
    rows = [({"invoice_total": 100.0}, {"invoice_total": "100"})]
    score = score_corpus(rows, _specs())
    assert score.fields["vendor_name"].tn == 1


# ── Wilson interval + tie detection ─────────────────────────────────────────


def test_wilson_interval_brackets_the_estimate():
    lo, hi = wilson_interval(18, 20)
    assert lo < 0.9 < hi
    assert 0.0 <= lo and hi <= 1.0
    assert lo == pytest.approx(0.699, abs=0.01)
    assert hi == pytest.approx(0.972, abs=0.01)


def test_wilson_interval_narrows_as_n_grows():
    small_lo, small_hi = wilson_interval(18, 20)
    big_lo, big_hi = wilson_interval(180, 200)
    assert (big_hi - big_lo) < (small_hi - small_lo)


def test_wilson_interval_handles_degenerate_inputs():
    assert wilson_interval(0, 0) == (0.0, 1.0)     # no data — total ignorance
    lo, hi = wilson_interval(20, 20)
    assert hi == pytest.approx(1.0) and lo < 1.0   # never claims certainty


def test_close_scores_on_small_n_are_tied():
    """0.900 vs 0.833 at n=20 is noise, and the leaderboard must not rank it."""
    assert intervals_overlap(wilson_interval(18, 20), wilson_interval(17, 20))


def test_clear_separation_on_large_n_is_not_tied():
    assert not intervals_overlap(wilson_interval(190, 200), wilson_interval(120, 200))


# ── determinism ─────────────────────────────────────────────────────────────


def test_scoring_is_deterministic():
    """Re-scoring cached output must never move the number. If it does, the
    leaderboard is not trustworthy."""
    rows = [
        ({"invoice_total": 100.0, "vendor_name": "Acme"},
         {"invoice_total": "$100.00", "vendor_name": "acme"}),
    ]
    first = score_corpus(rows, _specs()).macro_f1
    for _ in range(5):
        assert score_corpus(rows, _specs()).macro_f1 == first
