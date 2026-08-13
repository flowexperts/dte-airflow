"""Eval harness for extraction (plan 051).

Two pure modules, deliberately free of I/O so they can be unit-tested at
speed and reused from a script:

- `comparators` — the `assert` of the harness. Typed, formatting-tolerant
  comparison of one expected value against one actual value.
- `scoring`     — turns per-field verdicts into precision / recall / F1 and
  corpus-level macro-F1, plus the Wilson intervals the leaderboard uses to
  refuse to rank noise.

Nothing here calls a model. Extraction is non-deterministic; *scoring must
not be*, or a re-score of cached output would move and the leaderboard would
be worthless.
"""

from dte.evals.comparators import MatchResult, UnknownComparator, compare
from dte.evals.scoring import (
    CorpusScore,
    FieldMetrics,
    FieldSpec,
    intervals_overlap,
    score_corpus,
    score_field,
    wilson_interval,
)

__all__ = [
    "CorpusScore",
    "FieldMetrics",
    "FieldSpec",
    "MatchResult",
    "UnknownComparator",
    "compare",
    "intervals_overlap",
    "score_corpus",
    "score_field",
    "wilson_interval",
]
