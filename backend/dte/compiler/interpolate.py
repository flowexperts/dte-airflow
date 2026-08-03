"""Trigger-time parameter and system-variable interpolation.

`{{name}}` and `{{params.key}}` placeholders in step string fields are
resolved before the pipeline reaches the compiler. The compiler stays
unaware of variables — it only ever sees literal SQL.

Pipeline inputs are declared as `PipelineParam` on the pipeline. Values
supplied on the trigger request are coerced against the declared type
(input validation only — the resolved value is still substituted as a
string; the SQL author writes casts).
"""
from __future__ import annotations

import copy
import re
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dte.models.pipeline import Pipeline, PipelineParam

# Fields per op whose string contents may reference `{{...}}` placeholders.
# Filter/map expression strings are the only user-authored SQL surfaces today;
# other fields (rename mappings, retype targets, sort by) are field identifiers
# picked from schemas and don't warrant substitution here.
_STEP_STRING_FIELDS: dict[str, tuple[str, ...]] = {
    "filter": ("expr",),
    "map": ("expr",),  # ExpressionMapStep — LookupMapStep has no expr field
}

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")

SYSTEM_VAR_NAMES: frozenset[str] = frozenset(
    ["now", "today", "yesterday", "start_of_week", "start_of_month"]
)


class InterpolationError(ValueError):
    """Raised when a `{{var}}` placeholder can't be resolved."""


class ParamValidationError(ValueError):
    """Raised when a caller-supplied value fails type coercion or a
    required declared param is missing.

    Carries a structured payload so the API layer can surface a 422 with
    `{param, expected_type, got}`.
    """

    def __init__(self, message: str, *, param: str, expected_type: str, got: Any = None):
        super().__init__(message)
        self.param = param
        self.expected_type = expected_type
        self.got = got

    def payload(self) -> dict:
        return {
            "code": "param_validation_error",
            "param": self.param,
            "expected_type": self.expected_type,
            "got": self.got,
            "message": str(self),
        }


# ─── Coercion ────────────────────────────────────────────────────────────

_TRUE_VALS = {"true", "1", "yes"}
_FALSE_VALS = {"false", "0", "no"}


_SYSTEM_VAR_SENTINEL_RE = re.compile(r"^\{\{\s*([\w.]+)\s*\}\}$")


def coerce_param_value(raw: str, expected_type: str) -> str:
    """Validate `raw` parses as `expected_type`. Return the canonicalised
    string suitable for interpolation.

    Coercion is validation-only: the returned value is always a string so
    interpolation stays a pure text substitution. SQL authors cast
    explicitly (`'{{params.d}}'::date`).

    Trigger-time dynamic binding: if `raw` is a bare `{{<system_var>}}`
    sentinel (e.g. `{{today}}`), resolve against the current system
    context before coercing. Preserves late binding for scheduled runs.
    """
    if not isinstance(raw, str):
        raise ParamValidationError(
            f"expected string value, got {type(raw).__name__}",
            param="?", expected_type=expected_type, got=raw,
        )
    m = _SYSTEM_VAR_SENTINEL_RE.match(raw)
    if m:
        name = m.group(1)
        if name not in SYSTEM_VAR_NAMES:
            raise ParamValidationError(
                f"unknown system variable: {{{{{name}}}}}",
                param="?", expected_type=expected_type, got=raw,
            )
        raw = _system_context()[name]
    t = expected_type
    try:
        if t == "string":
            return raw
        if t == "int":
            return str(int(raw))
        if t == "float":
            return str(float(raw))
        if t == "boolean":
            v = raw.strip().lower()
            if v in _TRUE_VALS:
                return "true"
            if v in _FALSE_VALS:
                return "false"
            raise ValueError(f"not a boolean: {raw!r}")
        if t == "date":
            return date.fromisoformat(raw).isoformat()
        if t == "timestamp":
            return datetime.fromisoformat(raw).isoformat()
    except ParamValidationError:
        raise
    except (ValueError, TypeError) as e:
        raise ParamValidationError(
            f"cannot parse {raw!r} as {t}: {e}",
            param="?", expected_type=t, got=raw,
        )
    raise ParamValidationError(
        f"unknown param type: {t}",
        param="?", expected_type=t, got=raw,
    )


def _system_context() -> dict[str, str]:
    today = date.today()
    return {
        "now": datetime.now(timezone.utc).isoformat(),
        "today": today.isoformat(),
        "yesterday": (today - timedelta(days=1)).isoformat(),
        "start_of_week": (today - timedelta(days=today.weekday())).isoformat(),
        "start_of_month": today.replace(day=1).isoformat(),
    }


def resolve_context(
    pipeline: "Pipeline | None" = None,
    user_values: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the runtime context for a pipeline run.

    - Applies declared param defaults, then overrides with `user_values`.
    - Coerces each value against its declared type (raises `ParamValidationError`).
    - Rejects `user_values` keys that aren't declared on the pipeline.
    - Merges system vars.

    When `pipeline` is None, only system vars are populated (used by unit
    tests and code paths that don't need typed validation).
    """
    params_out: dict[str, str] = {}
    supplied = dict(user_values or {})

    if pipeline is not None:
        # `Pipeline(table=True)` construction skips Pydantic validators
        # (SQLModel 0.0.39 gotcha), so `.params` may still be raw dicts on
        # hydration. Normalise here.
        from dte.models.pipeline import PipelineParam as _PipelineParam
        declared: list[_PipelineParam] = [
            p if isinstance(p, _PipelineParam) else _PipelineParam.model_validate(p)
            for p in (pipeline.params or [])
        ]
        declared_names = {p.name for p in declared}
        unknown = set(supplied) - declared_names
        if unknown:
            first = sorted(unknown)[0]
            raise ParamValidationError(
                f"unknown param: {first!r} not declared on pipeline",
                param=first, expected_type="(undeclared)", got=supplied[first],
            )
        for decl in declared:
            if decl.name in supplied:
                raw = supplied[decl.name]
            elif decl.default is not None:
                raw = decl.default
            elif decl.required:
                raise ParamValidationError(
                    f"missing required param: {decl.name!r}",
                    param=decl.name, expected_type=decl.type, got=None,
                )
            else:
                continue  # optional + no default + not supplied → omit
            try:
                params_out[decl.name] = coerce_param_value(raw, decl.type)
            except ParamValidationError as e:
                # Re-raise with the real param name attached.
                raise ParamValidationError(
                    f"param {decl.name!r}: {e}",
                    param=decl.name, expected_type=decl.type, got=raw,
                ) from None
    else:
        # No pipeline: pass raw values through (used by legacy tests).
        params_out = {k: str(v) for k, v in supplied.items()}

    return {"params": params_out, **_system_context()}


def extract_param_refs(text: str) -> list[str]:
    """Return every `<path>` inside `{{ <path> }}` occurrences of `text`.

    Used by save-time validation to check that every reference resolves
    against declared params + system vars.
    """
    return [m.group(1) for m in _PLACEHOLDER_RE.finditer(text)]


def _lookup(context: dict[str, Any], path: str) -> str:
    parts = path.split(".")
    head, *rest = parts
    if head not in context:
        raise InterpolationError(f"unknown variable: {{{{{path}}}}}")
    value: Any = context[head]
    for seg in rest:
        if not isinstance(value, dict) or seg not in value:
            raise InterpolationError(f"unknown variable: {{{{{path}}}}}")
        value = value[seg]
    if isinstance(value, dict):
        raise InterpolationError(
            f"variable {{{{{path}}}}} resolved to a mapping, not a scalar"
        )
    return str(value)


def interpolate_text(text: str, context: dict[str, Any]) -> str:
    def _sub(m: re.Match[str]) -> str:
        return _lookup(context, m.group(1))

    return _PLACEHOLDER_RE.sub(_sub, text)


def interpolate_pipeline(pipeline: "Pipeline", context: dict[str, Any]) -> "Pipeline":
    """Return a copy of `pipeline` with `{{var}}` placeholders resolved in
    the string-valued fields of every step. Unknown variables raise
    `InterpolationError`.
    """
    from dte.models.pipeline import Pipeline as _Pipeline
    resolved_steps: list[dict] = []
    for step in pipeline.steps or []:
        op = step.get("op")
        fields = _STEP_STRING_FIELDS.get(op, ())
        if not fields:
            resolved_steps.append(step)
            continue
        new_step = copy.deepcopy(step)
        for f in fields:
            val = new_step.get(f)
            if isinstance(val, str):
                new_step[f] = interpolate_text(val, context)
        resolved_steps.append(new_step)

    data = pipeline.model_dump()
    data["steps"] = resolved_steps
    return _Pipeline(**data)
