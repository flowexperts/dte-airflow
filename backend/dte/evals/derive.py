"""An eval set derived from the pipeline that already declares the fields.

Plan 051 required the user to define their field list twice: once as the
structure step's `model.fields`, once as the eval set's `field_specs`. The
builder carried a warning about it — a name that doesn't match "won't
error; it scores zero on every document, which reads as a broken
extractor." That warning is an admission that the design was wrong. Two
hand-maintained copies of one list, where drift is silent and misattributed.

So the pipeline is the single definition and the eval set is derived from
it. Three choices carry this module:

**Derivation is one-directional.** Structure step → eval set, never back.
The two shapes are close but not equal — `field_specs` has `comparator`,
`model.fields` has `pattern`/`required`/`examples` — and a two-way sync
between similar-but-unequal shapes is precisely how the drift would return
wearing a different hat.

**An unknown type degrades to `string`, it does not raise.** A structure
type added in some later release would otherwise blow up mid-wizard on a
pipeline that saves fine. `string` is the most forgiving comparator, so the
failure mode is a field scored more leniently than it could be — visible in
the score, harmless to the run.

**`llm_judge` is never derived.** It bills on every row and it flatters an
extractor drawn from its own model family. Nothing should turn that on
because a wizard inferred it; it stays an explicit opt-in through the API.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

# Structure types are a strict subset of comparator types, but the names
# diverge where the concepts do: extraction cares whether a number is an
# int or a float, scoring does not — both compare with tolerance.
_TYPE_MAP: dict[str, str] = {
    "int": "numeric",
    "float": "numeric",
    "string": "string",
    "boolean": "boolean",
    "date": "date",
    "timestamp": "timestamp",
}

_FALLBACK_TYPE = "string"

# Formatting-forgiving, semantically strict — the rule the comparators were
# written to. `$1,240.50` matches `1240.5`; `1240.50` does not match
# `1204.50`. A non-zero relative tolerance here would quietly accept the
# second, so the default is exact-after-normalisation and users widen it
# per field when their domain genuinely needs it.
_NUMERIC_COMPARATOR: dict[str, float] = {"rel_tol": 0.0}


def _fields_of(step: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if step.get("op") != "structure":
        raise ValueError(
            "an eval set's fields come from a structure step, and this step "
            f"is {step.get('op')!r}"
        )
    model = step.get("model") or {}
    # Steps arrive as plain dicts off the wire but may be model objects when
    # read back through a parsed Pipeline. Accept both — otherwise the
    # wizard works on create and breaks on re-open.
    if not isinstance(model, Mapping):
        model = getattr(model, "model_dump", dict)()
    fields = list(model.get("fields") or [])
    if not fields:
        raise ValueError(
            "a structure step must declare at least one field — with none, "
            "there is nothing to score"
        )
    return [f if isinstance(f, Mapping) else f.model_dump() for f in fields]


def field_specs_from_structure(step: Mapping[str, Any]) -> list[dict]:
    """The eval `field_specs` implied by one `structure` step.

    Carries `name` and `description`. Drops `pattern`, `required` and
    `examples` — those steer how a value is obtained, and an eval set has no
    opinion about that; it only compares what came out.
    """
    specs: list[dict] = []
    for field in _fields_of(step):
        spec: dict[str, Any] = {
            "name": field["name"],
            "type": _TYPE_MAP.get(field.get("type") or "string", _FALLBACK_TYPE),
        }
        description = (field.get("description") or "").strip()
        if description:
            spec["description"] = description
        if spec["type"] == "numeric":
            spec["comparator"] = dict(_NUMERIC_COMPARATOR)
        specs.append(spec)
    return specs


def eval_set_fingerprint(source_id: str, specs: list[dict]) -> str:
    """A stable id for "this corpus, scored on these fields".

    Exists so that clicking Compare twice reuses one eval set instead of
    minting a second one with no labels in it. What is *in* the fingerprint
    is therefore a statement about when prior labels stop applying:

    - **Order is excluded.** Reordering fields in the builder is cosmetic.
      If it changed the fingerprint, the user would silently lose every
      label they had to a rename they did not make.
    - **`description` is excluded.** Descriptions steer the model, not the
      comparison. Rewording a prompt hint must not orphan the corpus — that
      is the single most common edit during prompt iteration, which is
      exactly when the labels matter most.
    - **`name`, `type` and `comparator` are included.** Each changes what
      "correct" means, so scores either side of the change are genuinely
      not comparable and a fresh set is the honest outcome.
    """
    material = sorted(
        (s["name"], s["type"], json.dumps(s.get("comparator") or {}, sort_keys=True))
        for s in specs
    )
    payload = json.dumps([source_id, material], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:12]
