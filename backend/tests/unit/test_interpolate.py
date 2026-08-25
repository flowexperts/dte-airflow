"""Tests for `dte.compiler.interpolate` — typed pipeline inputs + system vars."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from dte.compiler.interpolate import (
    InterpolationError,
    ParamValidationError,
    coerce_param_value,
    extract_param_refs,
    interpolate_pipeline,
    interpolate_text,
    resolve_context,
)
from dte.models.pipeline import Pipeline, PipelineParam


def _pipeline(steps: list[dict] | None = None, params: list[dict] | None = None) -> Pipeline:
    return Pipeline(
        id="p1", name="t", sources=["s"],
        steps=steps or [],
        params=params or [],
        output_id="out",
    )


# ─── System vars ────────────────────────────────────────────────────────

def test_resolve_context_system_vars():
    ctx = resolve_context()
    today = date.today()
    assert ctx["today"] == today.isoformat()
    assert ctx["yesterday"] == (today - timedelta(days=1)).isoformat()
    assert ctx["start_of_month"] == today.replace(day=1).isoformat()
    assert ctx["start_of_week"] == (today - timedelta(days=today.weekday())).isoformat()
    assert ctx["params"] == {}


def test_interpolate_text_substitutes_system_vars():
    ctx = resolve_context()
    out = interpolate_text("updated_at <= '{{today}}'", ctx)
    assert ctx["today"] in out


def test_interpolate_text_unknown_variable_raises():
    with pytest.raises(InterpolationError):
        interpolate_text("x > '{{params.missing}}'", resolve_context())


def test_interpolate_text_whitespace_inside_braces():
    ctx = resolve_context()
    # Bare (unquoted) date/timestamp sentinels get auto-quoted so the
    # emitted SQL is valid.
    assert interpolate_text("{{ today }}", ctx) == f"'{ctx['today']}'"


def test_interpolate_text_bare_sentinel_gets_quoted():
    ctx = resolve_context()
    out = interpolate_text('"ts" >= {{now}}', ctx)
    assert out == f"\"ts\" >= '{ctx['now']}'"


def test_interpolate_text_quoted_sentinel_not_double_quoted():
    ctx = resolve_context()
    out = interpolate_text("updated_at <= '{{today}}'", ctx)
    assert out == f"updated_at <= '{ctx['today']}'"


def test_interpolate_text_numeric_sentinel_passes_through_unquoted():
    ctx = {"params": {"qty": "42"}}
    assert interpolate_text("qty >= {{params.qty}}", ctx) == "qty >= 42"


# ─── Coercion ───────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,typ,expected",
    [
        ("hello", "string", "hello"),
        ("42", "int", "42"),
        ("3.14", "float", "3.14"),
        ("true", "boolean", "true"),
        ("FALSE", "boolean", "false"),
        ("1", "boolean", "true"),
        ("2024-07-01", "date", "2024-07-01"),
        ("2024-07-01T10:30:00", "timestamp", "2024-07-01T10:30:00"),
    ],
)
def test_coerce_param_value_ok(raw, typ, expected):
    assert coerce_param_value(raw, typ) == expected


@pytest.mark.parametrize(
    "raw,typ",
    [
        ("not-an-int", "int"),
        ("not-a-float", "float"),
        ("maybe", "boolean"),
        ("2024-13-40", "date"),
        ("nope", "timestamp"),
    ],
)
def test_coerce_param_value_rejects(raw, typ):
    with pytest.raises(ParamValidationError):
        coerce_param_value(raw, typ)


# ─── Declared-param resolution ──────────────────────────────────────────

def test_resolve_context_applies_declared_defaults_and_coerces():
    p = _pipeline(params=[
        {"name": "min", "type": "int", "required": False, "default": "10"},
        {"name": "flag", "type": "boolean", "required": False, "default": "yes"},
    ])
    ctx = resolve_context(p, {})
    assert ctx["params"] == {"min": "10", "flag": "true"}


def test_resolve_context_missing_required_raises():
    p = _pipeline(params=[
        {"name": "start_date", "type": "date", "required": True},
    ])
    with pytest.raises(ParamValidationError) as ei:
        resolve_context(p, {})
    assert ei.value.param == "start_date"
    assert ei.value.expected_type == "date"


def test_resolve_context_optional_no_default_omits():
    p = _pipeline(params=[
        {"name": "note", "type": "string", "required": False},
    ])
    ctx = resolve_context(p, {})
    assert "note" not in ctx["params"]


def test_resolve_context_rejects_undeclared():
    p = _pipeline()
    with pytest.raises(ParamValidationError):
        resolve_context(p, {"nope": "x"})


def test_resolve_context_type_mismatch_names_param():
    p = _pipeline(params=[
        {"name": "min", "type": "int", "required": True},
    ])
    with pytest.raises(ParamValidationError) as ei:
        resolve_context(p, {"min": "abc"})
    assert ei.value.param == "min"


# ─── Reference extraction + interpolation ───────────────────────────────

def test_extract_param_refs_finds_all():
    refs = extract_param_refs("x > {{params.a}} AND y < '{{today}}' AND z = {{params.b}}")
    assert refs == ["params.a", "today", "params.b"]


def test_interpolate_pipeline_rewrites_filter_and_map_expr():
    p = _pipeline(
        steps=[
            {"op": "filter", "expr": "amount > {{params.min}}"},
            {"op": "map", "mode": "expression", "output_field": "d",
             "expr": "date_diff('day', ts, '{{today}}'::date)"},
            {"op": "rename", "mappings": {"a": "b"}},
        ],
        params=[{"name": "min", "type": "int", "required": True}],
    )
    ctx = resolve_context(p, {"min": "10"})
    out = interpolate_pipeline(p, ctx)
    assert out.steps[0]["expr"] == "amount > 10"
    assert ctx["today"] in out.steps[1]["expr"]
    assert out.steps[2] == {"op": "rename", "mappings": {"a": "b"}}


def test_interpolate_pipeline_rewrites_check_expr():
    p = _pipeline(
        steps=[{"op": "check", "expr": "ts < '{{today}}'", "severity": "fail"}],
    )
    ctx = resolve_context(p)
    out = interpolate_pipeline(p, ctx)
    assert out.steps[0]["expr"] == f"ts < '{ctx['today']}'"


# ─── Dynamic trigger values ─────────────────────────────────────────────

def test_coerce_dynamic_today_resolves_to_date():
    out = coerce_param_value("{{today}}", "date")
    assert out == date.today().isoformat()


def test_coerce_dynamic_now_resolves_to_timestamp():
    out = coerce_param_value("{{now}}", "timestamp")
    # ISO string parses back as datetime
    from datetime import datetime
    datetime.fromisoformat(out)


def test_coerce_dynamic_with_whitespace():
    out = coerce_param_value("{{ today }}", "date")
    assert out == date.today().isoformat()


def test_coerce_dynamic_now_on_int_rejected():
    with pytest.raises(ParamValidationError):
        coerce_param_value("{{now}}", "int")


def test_coerce_dynamic_unknown_var_rejected():
    with pytest.raises(ParamValidationError):
        coerce_param_value("{{bogus}}", "string")


def test_resolve_context_dynamic_declared_param():
    p = _pipeline(params=[
        {"name": "as_of", "type": "date", "required": True},
    ])
    ctx = resolve_context(p, {"as_of": "{{today}}"})
    assert ctx["params"]["as_of"] == date.today().isoformat()


def test_interpolate_pipeline_leaves_lookup_map_untouched():
    p = _pipeline(steps=[
        {"op": "map", "mode": "lookup", "field": "id", "lookup_id": "lt1"},
    ])
    out = interpolate_pipeline(p, resolve_context(p))
    assert out.steps[0]["lookup_id"] == "lt1"


def test_interpolate_pipeline_rewrites_case_condition_values():
    p = _pipeline(
        steps=[{
            "op": "case", "output_field": "band",
            "branches": [{
                "when": [{"field": "amount", "op": ">", "value": "{{params.min}}"}],
                "then": "big",
            }],
        }],
        params=[{"name": "min", "type": "int", "required": True}],
    )
    ctx = resolve_context(p, {"min": "10"})
    out = interpolate_pipeline(p, ctx)
    assert out.steps[0]["branches"][0]["when"][0]["value"] == "10"


def test_interpolate_pipeline_rewrites_date_diff_to():
    p = _pipeline(steps=[{
        "op": "date_diff", "field": "dob", "to": "{{today}}",
        "unit": "year", "output_field": "age",
    }])
    ctx = resolve_context(p)
    out = interpolate_pipeline(p, ctx)
    # interpolate_text quotes a bare sentinel for the SQL surfaces; the
    # compiler strips it back off since `to` is a plain date literal.
    assert out.steps[0]["to"].strip("'") == ctx["today"]
