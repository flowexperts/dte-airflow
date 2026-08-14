"""Expanding a sweep matrix into real, runnable pipeline variants.

A sweep cell is only worth anything if it becomes a pipeline whose
`config_digest` differs from its siblings. The digest is what the
leaderboard groups by, so two cells that collapse to the same digest are
one config that overwrites itself and reports as a single row — a 4-cell
sweep that renders as one, with no error to explain the missing three.

Two rules keep that honest:

**Overrides are applied to a deep copy.** Cells are generated in a loop off
one base pipeline; mutating it in place would make each cell inherit the
previous cell's overrides, and the sweep would measure a diagonal through
the grid rather than the grid.

**An unknown axis raises.** Silently dropping a typo'd axis name produces N
identical cells that all score the same, which reads as "that setting makes
no difference" — a conclusion drawn from a spelling mistake, and one nobody
would think to double-check because the sweep completed cleanly.

Axis names are dotted paths into the `structure` step (`provider`,
`params.max_tokens`, `model.instructions`). That step is where the answer
is decided, and confining overrides to it means a sweep cannot accidentally
rewrite the source or the projection.

A **known** axis may be introduced where the base config never had one.
This is the ordinary case, not an edge: a `regex` step carries `params: {}`
because regex makes no model calls, so comparing it against claude needs a
`params.model` that does not exist yet. Refusing that rejected the most
natural comparison in the product — "is the model worth it over the regex I
already wrote?" — with a message naming a key the user never typed.

The allowlist is what keeps the guard intact while allowing this. A typo is
not on it, so `params.modle` still raises and the N-identical-cells failure
above still cannot happen.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from dte.evals.digest import config_digest

_STRUCTURE_OP = "structure"

# Dotted paths a sweep may *create* on the structure step, as opposed to
# merely overwrite. Everything here is a real key of `StructureStep`, so
# introducing one produces a config the model would accept had the user
# typed it themselves. Anything absent from this set must already exist.
_CREATABLE_AXES = frozenset({
    "params.model",
    "params.max_tokens",
    "params.api_key",
    "model.instructions",
})


def _structure_step(steps: list) -> dict | None:
    for step in steps:
        if isinstance(step, dict) and step.get("op") == _STRUCTURE_OP:
            return step
    return None


def detached_copy(pipeline: Any) -> Any:
    """A plain, session-free copy of a pipeline.

    `copy.deepcopy` is wrong here. A pipeline loaded from Postgres is a
    live SQLAlchemy-instrumented instance, and deep-copying it drags the
    instrumentation along; assigning to `.id` on the result then raises
    `ObjectDereferencedError` once the original is garbage collected. The
    fakes return detached instances, so this failed only against a real
    database — the worst place to find out.

    Rebuilding from `model_dump()` produces an ordinary instance with no
    identity map behind it, which is exactly what a sweep variant is.
    """
    dump = getattr(pipeline, "model_dump", None)
    if dump is None:
        return copy.deepcopy(pipeline)
    return type(pipeline)(**copy.deepcopy(dump()))


def apply_cell(pipeline: Any, cell: Mapping[str, Any]) -> Any:
    """Return a copy of `pipeline` with one sweep cell's overrides applied."""
    variant = detached_copy(pipeline)
    step = _structure_step(getattr(variant, "steps", None) or [])
    if step is None:
        raise ValueError(
            "a sweep varies the structure step's config, and this pipeline "
            "has no structure step"
        )

    for path, value in cell.items():
        path = str(path)
        head, *rest = path.split(".")
        creatable = path in _CREATABLE_AXES
        if head not in step and not creatable:
            raise ValueError(
                f"unknown sweep axis {path!r}: the structure step has no "
                f"{head!r}. Axes are dotted paths into that step, e.g. "
                "'provider' or 'model.instructions'."
            )
        target = step
        for part in [head, *rest][:-1]:
            nxt = target.get(part)
            # A creatable axis may need its parent dict too — `params: {}` is
            # normal on a regex step, but an absent `params` is equally valid.
            if nxt is None and creatable:
                nxt = target[part] = {}
            if not isinstance(nxt, dict):
                raise ValueError(
                    f"unknown sweep axis {path!r}: {part!r} is not a nested object"
                )
            target = nxt
        leaf = rest[-1] if rest else head
        if rest and leaf not in target and not creatable:
            raise ValueError(
                f"unknown sweep axis {path!r}: no {leaf!r} under {head!r}. "
                "Add it to the step, or check the spelling — a sweep will not "
                "invent a setting, since every cell would then score the same."
            )
        target[leaf] = value
    return variant


def variant_id(pipeline: Any, cell: Mapping[str, Any]) -> str:
    """A deterministic id for one cell, namespaced under the base pipeline.

    Derived from the digest rather than a counter so re-running the same
    sweep lands on the same row instead of accumulating a new pipeline per
    launch — and so a re-run hits the extract/structure cache rather than
    paying again for an identical config under a new name.
    """
    digest = config_digest(apply_cell(pipeline, cell))
    return f"{getattr(pipeline, 'id', 'sweep')}__{digest[:12]}"
