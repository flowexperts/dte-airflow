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
import re
from typing import Any, Mapping

from dte.evals.digest import config_digest

_STRUCTURE_OP = "structure"

# Exactly the shape `variant_id` appends: 12 lowercase hex characters.
# Narrow on purpose — see `root_pipeline_id`.
_VARIANT_SUFFIX = re.compile(r"[0-9a-f]{12}")

# Dotted paths a sweep may *create* on the structure step, as opposed to
# merely overwrite. Everything here is a real key of `StructureStep`, so
# introducing one produces a config the model would accept had the user
# typed it themselves. Anything absent from this set must already exist.
_CREATABLE_AXES = frozenset({
    "params.model",
    "params.max_tokens",
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


def validate_matrix_axes(steps: list, matrix: Mapping[str, Any]) -> None:
    """Raise if `matrix` names an axis a sweep could not apply.

    The same rule `apply_cell` enforces, hoisted so it can also run at *save*
    time. It used to fire only at spend — after a matrix had been typed,
    estimated and priced — which is late for a typo whose whole effect is N
    identical cells reading as "this setting makes no difference".

    Deliberately shares `_CREATABLE_AXES` and `_structure_step` with
    `apply_cell` rather than restating them: a save-time check that disagreed
    with the run-time one would either reject configs that work or accept
    configs that fail at the end of a paid sweep.
    """
    if not matrix:
        return
    step = _structure_step(steps)
    if step is None:
        raise ValueError(
            "a comparison matrix varies the structure step's config, and "
            "this pipeline has no structure step"
        )
    for path, values in matrix.items():
        path = str(path)
        if not isinstance(values, (list, tuple)):
            raise ValueError(
                f"matrix axis {path!r} must be a list of values to vary"
            )
        if len(values) == 0:
            # An empty axis contributes nothing to the product, so the user
            # gets fewer cells than they configured with nothing said.
            raise ValueError(
                f"matrix axis {path!r} has no values — remove the axis, or "
                "give it something to vary"
            )
        head = path.split(".")[0]
        if head not in step and path not in _CREATABLE_AXES:
            raise ValueError(
                f"unknown matrix axis {path!r}: the structure step has no "
                f"{head!r}. Axes are dotted paths into that step, e.g. "
                "'provider' or 'model.instructions'."
            )


# Axes a provider does not read. Sweeping one of these against that
# provider produces cells that differ on paper and are identical in fact.
_IGNORED_AXES: dict[str, frozenset[str]] = {
    "regex": frozenset({
        "params.model", "params.max_tokens", "model.instructions",
    }),
}

# Which provider owns a model name. Prefixes, not an enumeration: a model
# released after this was written must not be refused — the provider will
# reject it far more accurately than a table here can.
_MODEL_OWNER: dict[str, str] = {"claude-": "claude", "gpt-": "openai"}


def _owner_of(model: str) -> str | None:
    for prefix, provider in _MODEL_OWNER.items():
        if model.startswith(prefix):
            return provider
    return None


def prune_cells(pipeline: Any, cells: list[dict]) -> tuple[list[dict], list[dict]]:
    """Reduce an expanded matrix to the configs that are actually distinct.

    `_expand_matrix` is a blind cartesian product, which is right for
    independent axes and wrong the moment one axis makes another
    irrelevant. `provider: [claude, regex] × params.model: [haiku, sonnet]`
    expands to four cells, two of which set a model on `regex` — a provider
    that never reads one. Those two are one config, run and billed twice,
    rendered as two columns labelled with models they did not use.

    That is the same failure the unknown-axis guard prevents — N cells
    scoring identically, reading as "this setting makes no difference" —
    reached from a direction the guard cannot see, since the axis genuinely
    exists on the step.

    Two rules:

    **Strip overrides the resolved provider ignores, then collapse
    duplicates.** Ticking regex alongside two models means "compare regex
    against them", not "run regex twice".

    **Drop a cell whose model belongs to another provider.** `claude` with
    `gpt-5` cannot run. Rewriting it to claude's default would report a
    number under a config nobody chose.

    Returns `(kept, dropped)`, where each dropped entry carries the cell and
    a reason — nothing disappears silently.
    """
    step = _structure_step(getattr(pipeline, "steps", None) or []) or {}
    base_provider = step.get("provider") or "claude"

    kept: list[dict] = []
    dropped: list[dict] = []
    seen: set[tuple] = set()

    for cell in cells:
        provider = cell.get("provider") or base_provider
        model = cell.get("params.model")
        if model:
            owner = _owner_of(str(model))
            if owner is not None and provider in _MODEL_OWNER.values() and owner != provider:
                dropped.append({
                    "cell": dict(cell),
                    "reason": (
                        f"{model!r} is a {owner} model and this cell runs on "
                        f"{provider!r} — the combination cannot run"
                    ),
                })
                continue

        ignored = _IGNORED_AXES.get(provider, frozenset())
        pruned = {k: v for k, v in cell.items() if k not in ignored}
        key = tuple(sorted(pruned.items(), key=lambda kv: str(kv[0])))
        if key in seen:
            removed = sorted(set(cell) & ignored)
            dropped.append({
                "cell": dict(cell),
                "reason": (
                    f"{provider!r} does not read {', '.join(removed)}, so this "
                    "cell is identical to one already in the sweep"
                ),
            })
            continue
        seen.add(key)
        kept.append(pruned)

    return kept, dropped


def root_pipeline_id(pipeline_id: str) -> str:
    """Strip sweep-variant suffixes back to the config someone authored.

    Sweep cells become real pipelines named `<base>__<digest12>`, and they
    appear in the pipeline list carrying their own Compare button. Without
    this, comparing a variant nested it under itself:

        demo_eval_strict__27fb9c1d2679__27fb9c1d2679__37f7b8bbec71

    Matching is deliberately narrow — exactly twelve lowercase hex
    characters. A user's own id that merely ends in `__2024` or `__abc`
    keeps it, because stripping one would file their sweeps under a
    pipeline that does not exist.

    `__eval` is not a variant suffix and survives: the twin is the thing
    people compare *from*, and collapsing it would point variants at the
    transform pipeline, which the corpus-match rule then refuses.
    """
    parts = pipeline_id.split("__")
    while len(parts) > 1 and _VARIANT_SUFFIX.fullmatch(parts[-1]):
        parts.pop()
    return "__".join(parts)


def variant_id(pipeline: Any, cell: Mapping[str, Any]) -> str:
    """A deterministic id for one cell, namespaced under the root pipeline.

    Derived from the digest rather than a counter so re-running the same
    sweep lands on the same row instead of accumulating a new pipeline per
    launch — and so a re-run hits the extract/structure cache rather than
    paying again for an identical config under a new name.

    The *namespace* is rooted; the *digest* is not. A variant of a variant
    inherits its parent's overrides, so its config genuinely differs from
    the same cell applied to the root and must not collide with it — one of
    the two would silently overwrite the other and a cell would vanish from
    the comparison with no error.
    """
    digest = config_digest(apply_cell(pipeline, cell))
    root = root_pipeline_id(str(getattr(pipeline, "id", "sweep")))
    return f"{root}__{digest[:12]}"


def variant_name(pipeline: Any, cell: Mapping[str, Any]) -> str:
    """Human label for one cell: the root config, then this cell's overrides.

    Names accumulated the same way ids did — "demo eval strict ·
    instructions=v3 · provider=regex · provider=claude, model=haiku" — which
    reads as a config varying four things when it varies one.
    """
    name = str(getattr(pipeline, "name", "") or getattr(pipeline, "id", "sweep"))
    pid = str(getattr(pipeline, "id", ""))
    if pid != root_pipeline_id(pid):
        # This pipeline is itself a cell; drop the suffix a previous sweep
        # appended so the new name describes the root plus this cell only.
        name = name.rsplit(" · ", 1)[0]
    return f"{name} · {cell_label(cell)}"


def cell_label(cell: Mapping[str, Any]) -> str:
    """`provider=claude, model=haiku` — the last segment of each axis path."""
    return ", ".join(f"{str(k).split('.')[-1]}={v}" for k, v in cell.items())
