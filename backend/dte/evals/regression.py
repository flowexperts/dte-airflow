"""Eval regression check, run by the operator after an eval pipeline scores."""
from __future__ import annotations

# Default drop, in F1 points, that counts as a regression.
EVAL_REGRESSION_THRESHOLD = 0.03


def detect_eval_regression(
    history: list[dict], digest: str, labels_version: int, run_id: str, scores: dict
) -> dict | None:
    """Compare against the most recent completed run at the same digest.

    Gated on three things, all of which must hold before this warns:

    - **Same `config_digest`** — otherwise the "regression" is just a config
      change, which is a result, not an alert.
    - **Same `labels_version`** — comparing across a label edit measures the
      labels, not the extractor.
    - **The drop clears the Wilson interval** — a nightly job that pages
      someone on sampling noise gets muted within a week.
    """
    current = scores.get("macro_f1")
    if current is None:
        return None
    for prior in history:
        if prior.get("id") == run_id:
            continue
        if prior.get("config_digest") != digest:
            continue
        if prior.get("labels_version") != labels_version:
            continue
        prior_scores = prior.get("scores") or {}
        previous = prior_scores.get("macro_f1")
        if previous is None:
            continue

        drop = previous - current
        if drop < EVAL_REGRESSION_THRESHOLD:
            return None

        lo, hi = (scores.get("macro_f1_interval") or [0.0, 1.0])[:2]
        prior_interval = prior_scores.get("macro_f1_interval") or [0.0, 1.0]
        if prior_interval[0] <= hi and lo <= prior_interval[1]:
            return None  # intervals overlap: not distinguishable from noise

        return {
            "previous_run_id": prior.get("id"),
            "previous_macro_f1": previous,
            "current_macro_f1": current,
            "drop": drop,
            "threshold": EVAL_REGRESSION_THRESHOLD,
        }
    return None
