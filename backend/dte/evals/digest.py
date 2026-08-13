"""`config_digest` — a stable identity for an extraction config (plan 051).

This is the single mechanism that makes drift detectable. Same digest + same
`labels_version` + a different score later means the *provider* changed under
you, which is the most valuable thing a scheduled eval can tell you and is
invisible without it.

Two decisions define what the digest covers:

**Only `extract` and `structure` steps.** Those are what determine the answer
the model gives. A `select` or `filter` after `structure` changes what gets
delivered, not what was asked — folding it in would report drift every time
someone reorders a projection.

**Not the pipeline's identity.** Two pipelines with identical extract and
structure steps are the same cell of a sweep and must compare against each
other. Keying on `pipeline_id` would make every duplicate look like a new
config and silently break the comparison the digest exists to enable.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

# The ops whose configuration decides the model's answer.
_SCORED_OPS = ("extract", "structure")


def canonical_config(pipeline: Any) -> list[dict]:
    """The extract/structure steps, in order, with keys sorted.

    Order is preserved — two extract steps swapped is a different pipeline —
    but key order within a step is not, so a config that differs only in how
    the UI happened to serialise it does not read as drift.
    """
    steps = getattr(pipeline, "steps", None) or []
    return [
        _sorted_deep(step)
        for step in steps
        if isinstance(step, dict) and step.get("op") in _SCORED_OPS
    ]


def _sorted_deep(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _sorted_deep(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_sorted_deep(v) for v in value]
    return value


def config_digest(pipeline: Any) -> str:
    """sha256 over the canonicalised extract + structure steps."""
    payload = json.dumps(
        canonical_config(pipeline),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
