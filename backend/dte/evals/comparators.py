"""Typed, formatting-tolerant comparison of one expected value to one actual.

This is the `assert` of the eval harness, and the place a naive implementation
quietly lies: `"$1,240.50" == 1240.50` is False in Python and True in every
sense that matters to a user reading an invoice.

Design rules:

- **Forgiving on formatting, strict on semantics.** Currency symbols, thousands
  separators, trailing zeros, case, and whitespace are noise. A transposed
  digit is not.
- **Pure.** No I/O, no clock, no model. Extraction is non-deterministic;
  scoring must not be, or a re-score of cached output would move.
- **Nulls are not handled here.** `compare` is only ever called on two non-null
  values — abstention bookkeeping belongs to `scoring`, where it becomes
  visible as the difference between a true negative and a false negative.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import Any


class UnknownComparator(ValueError):
    """No comparator is registered for the requested field type."""


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    score: float
    reason: str


_MATCH = MatchResult(True, 1.0, "exact match after normalization")


# ── numeric ─────────────────────────────────────────────────────────────────

# Keep digits, minus, and dot. Strips currency symbols/codes, thousands
# separators, and whitespace. Deliberately US-style: "1.240,50" is ambiguous
# with "1240.50" and guessing is how a whole corpus flips silently.
_NUM_STRIP = re.compile(r"[^\d.\-]")


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = _NUM_STRIP.sub("", str(value))
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _compare_numeric(expected: Any, actual: Any, opts: dict) -> MatchResult:
    exp = _to_number(expected)
    act = _to_number(actual)
    if exp is None:
        return MatchResult(False, 0.0, f"could not parse expected {expected!r} as a number")
    if act is None:
        return MatchResult(False, 0.0, f"could not parse {actual!r} as a number")

    abs_tol = opts.get("abs_tol", 0.005)
    rel_tol = opts.get("rel_tol", 0.0)
    delta = abs(exp - act)
    allowed = max(abs_tol, abs(exp) * rel_tol)
    if delta <= allowed:
        return MatchResult(True, 1.0, f"within tolerance ({delta:g} <= {allowed:g})")
    return MatchResult(False, 0.0, f"differs by {delta:g} (tolerance {allowed:g})")


# ── date ────────────────────────────────────────────────────────────────────


# A leading 4-digit year means the format is year-first and unambiguous
# (`2024-03-01`, `2024/03/01`). Passing dayfirst=True to dateutil for these
# makes it read ISO as year-DAY-month, which silently corrupted the *expected*
# side of every comparison — the labels, not the extraction.
_YEAR_FIRST = re.compile(r"^\s*\d{4}[-/]")


def _to_date(value: Any, dayfirst: bool) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    from dateutil import parser as _dateparser

    text = str(value)
    try:
        if _YEAR_FIRST.match(text):
            return _dateparser.parse(text, yearfirst=True, dayfirst=False).date()
        return _dateparser.parse(text, dayfirst=dayfirst).date()
    except (ValueError, OverflowError, TypeError):
        return None


def _compare_date(expected: Any, actual: Any, opts: dict) -> MatchResult:
    # `01/03/2024` is genuinely ambiguous. The flag is load-bearing: set it
    # wrong and every date in the corpus flips without any error surfacing.
    dayfirst = opts.get("dayfirst", True)
    exp = _to_date(expected, dayfirst)
    act = _to_date(actual, dayfirst)
    if exp is None:
        return MatchResult(False, 0.0, f"could not parse expected {expected!r} as a date")
    if act is None:
        return MatchResult(False, 0.0, f"could not parse {actual!r} as a date")

    day_tol = int(opts.get("day_tol", 0))
    delta = abs((exp - act).days)
    if delta <= day_tol:
        return MatchResult(True, 1.0, f"same date (±{day_tol}d)")
    return MatchResult(False, 0.0, f"{act.isoformat()} != {exp.isoformat()} ({delta}d apart)")


# ── string ──────────────────────────────────────────────────────────────────

_WS = re.compile(r"\s+")
_TRAILING_PUNCT = re.compile(r"[.,;:]+$")


def _normalize_str(value: Any) -> str:
    # NFKC folds non-breaking spaces and other compatibility forms into their
    # plain equivalents, so "Acme Industrial" == "Acme Industrial".
    text = unicodedata.normalize("NFKC", str(value))
    text = _WS.sub(" ", text).strip().casefold()
    return _TRAILING_PUNCT.sub("", text)


def _compare_string(expected: Any, actual: Any, opts: dict) -> MatchResult:
    if opts.get("normalize", True):
        exp, act = _normalize_str(expected), _normalize_str(actual)
    else:
        exp, act = str(expected), str(actual)

    if exp == act:
        return _MATCH

    threshold = opts.get("fuzzy_threshold")
    if threshold is not None:
        ratio = SequenceMatcher(None, exp, act).ratio()
        if ratio >= threshold:
            return MatchResult(True, ratio, f"fuzzy match (ratio {ratio:.3f} >= {threshold})")
        return MatchResult(False, ratio, f"fuzzy ratio {ratio:.3f} < {threshold}")
    return MatchResult(False, 0.0, f"{act!r} != {exp!r} after normalization")


def _compare_enum(expected: Any, actual: Any, opts: dict) -> MatchResult:
    if str(expected).strip().casefold() == str(actual).strip().casefold():
        return _MATCH
    return MatchResult(False, 0.0, f"{actual!r} is not {expected!r}")


# ── list / set ──────────────────────────────────────────────────────────────


def _as_set(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = [p for p in str(value).split(",")]
    return {_normalize_str(item) for item in items if str(item).strip()}


def _compare_list(expected: Any, actual: Any, opts: dict) -> MatchResult:
    exp, act = _as_set(expected), _as_set(actual)
    threshold = opts.get("jaccard_threshold")
    if threshold is None:
        if exp == act:
            return _MATCH
        return MatchResult(False, 0.0, f"set mismatch: missing {sorted(exp - act)}, extra {sorted(act - exp)}")

    union = exp | act
    jaccard = len(exp & act) / len(union) if union else 1.0
    if jaccard >= threshold:
        return MatchResult(True, jaccard, f"jaccard {jaccard:.3f} >= {threshold}")
    return MatchResult(False, jaccard, f"jaccard {jaccard:.3f} < {threshold}")


# ── registry ────────────────────────────────────────────────────────────────
#
# Flat name→callable, shaped like `sources/loader.py`'s LOADERS. Adding a
# comparator is one function plus one entry. `llm_judge` is deliberately
# absent — it needs a provider and a cache, and it belongs with the labeling
# work, not here.

_COMPARATORS = {
    "numeric": _compare_numeric,
    "int": _compare_numeric,
    "float": _compare_numeric,
    "date": _compare_date,
    "timestamp": _compare_date,
    "string": _compare_string,
    "str": _compare_string,
    "enum": _compare_enum,
    "boolean": _compare_enum,
    "list": _compare_list,
    "set": _compare_list,
}

# The field types a spec may declare. Exported so an eval set can reject an
# unknown comparator at save time rather than at the end of a paid sweep.
COMPARATOR_TYPES: frozenset[str] = frozenset(_COMPARATORS)


def compare(
    expected: Any,
    actual: Any,
    field_type: str,
    opts: dict | None = None,
) -> MatchResult:
    """Compare one expected value to one actual value under `field_type`.

    Raises `ValueError` if either side is None — null bookkeeping belongs to
    `scoring`, and silently treating None as a mismatch here would hide the
    difference between correct abstention and a silent miss.
    """
    if expected is None or actual is None:
        raise ValueError(
            "compare() takes two non-null values; null handling belongs to "
            "dte.evals.scoring so abstention stays distinguishable from a miss"
        )
    fn = _COMPARATORS.get(field_type)
    if fn is None:
        raise UnknownComparator(
            f"no comparator for field type {field_type!r}; "
            f"known types: {', '.join(sorted(_COMPARATORS))}"
        )
    return fn(expected, actual, opts or {})
