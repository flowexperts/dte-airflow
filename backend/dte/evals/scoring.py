"""Turn per-field verdicts into rankable numbers.

The whole reason this module reports precision and recall rather than accuracy:
**an extractor that answers "I don't know" to everything is never wrong.**
Score it as "of the answers it gave, how many were right?" and it gets 100%.
Distinguishing correct abstention from a silent miss is the entire job.

Classification of each (expected, actual) pair:

    expected non-null, matched          → tp
    expected non-null, wrong answer     → fp AND fn   (see note below)
    expected non-null, actual null      → fn          (silent miss)
    expected null,     actual non-null  → fp          (hallucination)
    expected null,     actual null      → tn          (correct abstention)

**Note on wrong answers.** Plan 051 originally specified a wrong answer as a
false positive only. That is wrong: it lets an extractor that answers every
row incorrectly report perfect recall, because nothing was ever "missed". A
wrong answer is two failures — an incorrect emission *and* a failure to produce
the right value — so it counts as both, which is also the standard convention
in extraction evaluation. Every acceptance assertion in the plan still holds
under this definition; see `test_scoring.py`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from dte.evals.comparators import compare

Z_95 = 1.959963984540054


@dataclass(frozen=True)
class FieldSpec:
    """One field under evaluation. Mirrors the `structure` step's data model
    plus the comparator config, because the task definition and the scoring
    definition are the same thing and must not drift."""

    name: str
    type: str
    comparator: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FieldMetrics:
    """Counts and derived rates for one field over a corpus.

    `precision`, `recall` and `f1` are `None` — not 0.0 and not 1.0 — when
    their denominator is empty. An undefined score must never be rendered as
    a real one.
    """

    name: str
    tp: int
    fp: int
    fn: int
    tn: int
    n: int
    # `fn` mixes silent misses with wrong answers, so the null count is tracked
    # separately for `null_rate` to stay meaningful. Must stay last — the
    # preceding fields have no defaults.
    fn_null: int = 0

    @property
    def precision(self) -> float | None:
        answered = self.tp + self.fp
        return self.tp / answered if answered else None

    @property
    def recall(self) -> float | None:
        expected = self.tp + self.fn
        return self.tp / expected if expected else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or (p + r) == 0:
            return 0.0 if (p is not None and r is not None) else None
        return 2 * p * r / (p + r)

    @property
    def exact_match_rate(self) -> float | None:
        return self.tp / self.n if self.n else None

    @property
    def null_rate(self) -> float | None:
        """Share of documents the extractor declined to answer."""
        if not self.n:
            return None
        return (self.fn_null + self.tn) / self.n

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn,
            "n": self.n,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "exact_match_rate": self.exact_match_rate,
            "null_rate": self.null_rate,
        }


@dataclass(frozen=True)
class CorpusScore:
    macro_f1: float | None
    fields: dict[str, FieldMetrics]
    n: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "macro_f1": self.macro_f1,
            "n": self.n,
            "fields": {k: v.as_dict() for k, v in self.fields.items()},
        }


def score_field(
    pairs: Iterable[tuple[Any, Any]],
    field_type: str,
    opts: dict | None = None,
    name: str = "",
) -> FieldMetrics:
    """Score one field over `(expected, actual)` pairs — one pair per document."""
    tp = fp = fn = tn = fn_null = n = 0

    for expected, actual in pairs:
        n += 1
        exp_null, act_null = expected is None, actual is None

        if exp_null and act_null:
            tn += 1
        elif exp_null:
            fp += 1                       # hallucinated a value
        elif act_null:
            fn += 1
            fn_null += 1                  # silent miss
        elif compare(expected, actual, field_type, opts).matched:
            tp += 1
        else:
            fp += 1                       # emitted something incorrect
            fn += 1                       # and failed to produce the right value

    return FieldMetrics(
        name=name, tp=tp, fp=fp, fn=fn, tn=tn, n=n, fn_null=fn_null
    )


def score_corpus(
    rows: Sequence[tuple[dict, dict]],
    specs: Sequence[FieldSpec],
) -> CorpusScore:
    """Score every field over `(expected_row, actual_row)` pairs.

    Macro-F1, not micro: one field with 100 easy rows must not drown out a
    field with 2 hard ones. A field missing from a row reads as null, so an
    extractor that omits a key is scored the same as one that returns null
    for it.
    """
    metrics: dict[str, FieldMetrics] = {}
    for spec in specs:
        pairs = [
            (expected.get(spec.name), actual.get(spec.name))
            for expected, actual in rows
        ]
        metrics[spec.name] = score_field(
            pairs, spec.type, spec.comparator, name=spec.name
        )

    scored = [m.f1 for m in metrics.values() if m.f1 is not None]
    macro_f1 = sum(scored) / len(scored) if scored else None
    return CorpusScore(macro_f1=macro_f1, fields=metrics, n=len(rows))


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Used so the leaderboard can refuse to rank noise. Wilson rather than the
    normal approximation because it stays inside [0, 1] and behaves at the
    extremes, where small eval sets actually live.
    """
    if n <= 0:
        return (0.0, 1.0)                 # no data — total ignorance, not certainty

    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def intervals_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """True when two confidence intervals overlap — i.e. the difference between
    the two estimates is not distinguishable from sampling noise.

    The leaderboard renders overlapping configs as tied rather than awarding a
    rank-1 badge. A leaderboard that declares winners on n=8 is worse than no
    leaderboard.
    """
    return a[0] <= b[1] and b[0] <= a[1]
