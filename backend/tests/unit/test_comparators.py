"""Comparators are the `assert` of the eval harness.

Every case here is a lie the harness would otherwise tell: a correct
extraction scored as wrong because the formatting differed, or a wrong one
scored as right because the comparison was too loose.
"""

import pytest

from dte.evals.comparators import UnknownComparator, compare


# ── numeric ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expected,actual",
    [
        (1240.50, "$1,240.50"),      # currency symbol + thousands separator
        (1240.50, "1240.5"),         # trailing-zero difference
        (1240.50, " 1240.50 "),      # surrounding whitespace
        (1240.50, "1,240.50"),       # separator only
        (1240.50, "USD 1240.50"),    # currency code prefix
        (-42.0, "-42"),              # negative
        (0.0, "0.00"),               # zero
        (1240.50, 1240.5),           # already numeric
    ],
)
def test_numeric_matches_across_formatting(expected, actual):
    assert compare(expected, actual, "numeric").matched


@pytest.mark.parametrize(
    "expected,actual",
    [
        (1240.50, "1204.50"),        # transposed digits — a real extraction error
        (1240.50, "124.05"),         # decimal shifted
        (1240.50, "12405"),          # separator eaten
        (42.0, "-42"),               # sign flipped
    ],
)
def test_numeric_rejects_wrong_values(expected, actual):
    assert not compare(expected, actual, "numeric").matched


def test_numeric_tolerance_is_configurable():
    assert compare(100.0, "100.004", "numeric", {"abs_tol": 0.01}).matched
    assert not compare(100.0, "100.02", "numeric", {"abs_tol": 0.01}).matched
    assert compare(1000.0, "1005", "numeric", {"rel_tol": 0.01}).matched
    assert not compare(1000.0, "1050", "numeric", {"rel_tol": 0.01}).matched


def test_numeric_unparseable_actual_does_not_match():
    result = compare(1240.50, "see attached", "numeric")
    assert not result.matched
    assert "parse" in result.reason.lower()


# ── date ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "actual",
    ["2024-03-01", "01/03/2024", "March 1, 2024", "1 March 2024", "2024/03/01"],
)
def test_date_matches_across_formats(actual):
    """`dayfirst` defaults to True here so 01/03/2024 reads as 1 March."""
    assert compare("2024-03-01", actual, "date", {"dayfirst": True}).matched


def test_date_dayfirst_changes_interpretation():
    """01/03/2024 is genuinely ambiguous. The flag is load-bearing: set it
    wrong and scores flip silently across the whole corpus."""
    assert compare("2024-03-01", "01/03/2024", "date", {"dayfirst": True}).matched
    assert compare("2024-01-03", "01/03/2024", "date", {"dayfirst": False}).matched


def test_date_rejects_different_dates():
    assert not compare("2024-03-01", "2024-03-02", "date").matched
    assert not compare("2024-03-01", "2023-03-01", "date").matched


def test_date_day_tolerance():
    assert compare("2024-03-01", "2024-03-03", "date", {"day_tol": 3}).matched
    assert not compare("2024-03-01", "2024-03-09", "date", {"day_tol": 3}).matched


def test_date_ignores_time_component():
    assert compare("2024-03-01", "2024-03-01T14:33:02Z", "date").matched


def test_date_unparseable_does_not_match():
    assert not compare("2024-03-01", "sometime in March", "date").matched


# ── string ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "expected,actual",
    [
        ("Acme Industrial Supply Co.", "Acme Industrial Supply Co"),   # trailing period
        ("Acme Industrial", "  Acme   Industrial  "),                  # collapsed whitespace
        ("Acme Industrial", "ACME INDUSTRIAL"),                        # case
        ("Acme Industrial", "Acme Industrial"),                   # non-breaking space
        ("Acme Industrial", "Acme\tIndustrial"),                       # tab
    ],
)
def test_string_normalizes_before_comparing(expected, actual):
    assert compare(expected, actual, "string").matched


def test_string_rejects_different_values():
    assert not compare("Acme Industrial", "Acme Industries", "string").matched


def test_string_exact_mode_disables_normalization():
    assert not compare("Acme", "ACME", "string", {"normalize": False}).matched


def test_string_fuzzy_threshold():
    opts = {"fuzzy_threshold": 0.85}
    assert compare("Acme Industrial Supply", "Acme Industrial Suply", "string", opts).matched
    assert not compare("Acme Industrial Supply", "Globex Corporation", "string", opts).matched


# ── enum ────────────────────────────────────────────────────────────────────


def test_enum_case_insensitive():
    assert compare("PAID", "paid", "enum").matched
    assert not compare("PAID", "pending", "enum").matched


# ── list / set ──────────────────────────────────────────────────────────────


def test_list_exact_set_equality_ignores_order():
    assert compare(["a", "b"], ["b", "a"], "list").matched
    assert not compare(["a", "b"], ["a"], "list").matched


def test_list_jaccard_threshold():
    opts = {"jaccard_threshold": 0.5}
    assert compare(["a", "b", "c"], ["a", "b", "d"], "list", opts).matched
    assert not compare(["a", "b", "c"], ["x", "y", "z"], "list", opts).matched


# ── nulls and unknown types ─────────────────────────────────────────────────


def test_null_handling_is_the_scorers_job_not_the_comparators():
    """`compare` is only ever called on two non-null values. Null bookkeeping
    (tn vs fn vs fp) belongs to scoring, which is where abstention becomes
    visible."""
    with pytest.raises(ValueError):
        compare(None, "x", "string")
    with pytest.raises(ValueError):
        compare("x", None, "string")


def test_unknown_field_type_raises():
    with pytest.raises(UnknownComparator):
        compare("a", "b", "quaternion")


def test_comparators_are_pure():
    """Scoring must be deterministic even though extraction is not — a
    re-score of cached output must never move."""
    for _ in range(5):
        assert compare(1240.50, "$1,240.50", "numeric").matched
        assert compare("2024-03-01", "March 1, 2024", "date").matched
