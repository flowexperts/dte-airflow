"""LLM-as-judge scoring for free-text fields.

Some fields cannot be compared any other way. A summary, a reason, a
description — two correct answers rarely share a wording, so exact match
scores them near zero and reads as a broken extractor rather than as the
wrong comparator. A judge is the only honest option there.

It is also the most dangerous thing in this module, for two reasons that
shape the whole design:

**Non-determinism would undermine the harness's load-bearing property.**
Plan 051 asserts that re-scoring a cached run reproduces its number
exactly; if it doesn't, no leaderboard comparison means anything. A model
call is not deterministic, so every verdict is cached on
`(expected, actual, judge_config)`. Re-scoring never re-asks, and a
leaderboard cannot change when nothing changed.

**A judge flatters an extractor it shares a family with.** So it is never
a default: a field is scored this way only when its spec says so, and the
UI marks those fields distinctly.

The judge callable is injected rather than imported. Scoring stays pure
and offline by default — the entire unit suite runs with no provider
configured — and a missing judge raises instead of degrading to string
equality, because a silent degradation would look exactly like a bad
extractor.
"""
from __future__ import annotations

import json
from typing import Any, Callable

# (expected, actual, opts) -> (matched, reason)
JudgeFn = Callable[[str, str, dict], "tuple[bool, str]"]

_judge: JudgeFn | None = None
_cache: dict[str, tuple[bool, str]] = {}


class JudgeUnavailable(RuntimeError):
    """Raised when an `llm_judge` field is scored with no judge configured.

    Deliberately loud. Falling back to string equality would score a
    free-text field near zero and present it as an extraction failure,
    sending someone to debug a prompt when the real problem is
    configuration.
    """


def set_judge(fn: JudgeFn | None) -> None:
    """Install (or clear) the judge callable."""
    global _judge
    _judge = fn


def clear_judge_cache() -> None:
    _cache.clear()


def _key(expected: str, actual: str, opts: dict) -> str:
    # Options are part of the key: tightening a rubric must re-judge rather
    # than silently reuse a verdict reached under the old one.
    return json.dumps([expected, actual, opts], sort_keys=True, default=str)


def judge_equivalent(expected: Any, actual: Any, opts: dict | None = None) -> tuple[bool, str]:
    """Ask the configured judge whether two free-text answers agree."""
    opts = opts or {}
    exp, act = str(expected), str(actual)

    # Identical text needs no model. On a large corpus this is most of the
    # bill, and paying to confirm a string equals itself is pure waste.
    if exp == act:
        return True, "identical text"

    key = _key(exp, act, opts)
    if key in _cache:
        return _cache[key]

    if _judge is None:
        raise JudgeUnavailable(
            "this field is scored with llm_judge but no judge is configured. "
            "Set one with dte.evals.judge.set_judge(); scoring will not fall "
            "back to string equality, which would report a configuration "
            "problem as an extraction failure."
        )

    verdict = _judge(exp, act, opts)
    _cache[key] = verdict
    return verdict
