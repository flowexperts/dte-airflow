"""Typed steps (plan 088): one discriminated union, strict on write, lenient
on read, and one ALLOWED_OPS table the validator and the UI both read."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from dte.api.main import app
from dte.errors import CompilerError
from dte.models.pipeline import (
    ALLOWED_OPS,
    STEP_OPS,
    ExpressionMapStep,
    LookupMapStep,
    PipelineBase,
    UnknownStep,
    parse_step,
)

# One valid step per tag, so every arm of the union is exercised.
_EXAMPLES = [
    {"op": "filter", "expr": "a > 1"},
    {"op": "rename", "mappings": {"a": "b"}},
    {"op": "retype", "field": "a", "to_type": "int"},
    {"op": "map", "mode": "lookup", "field": "a", "lookup_id": "lt"},
    {"op": "map", "mode": "expression", "output_field": "x", "expr": "a + 1"},
    {"op": "map", "mode": "calculation", "output_field": "x", "expr": "a * 2"},
    {"op": "case", "output_field": "t", "branches": [{"when": [{"field": "a"}], "then": 1}]},
    {"op": "sort", "by": ["a"]},
    {"op": "aggregate", "group_by": ["a"], "aggregations": [{"field": "b", "func": "sum", "alias": "s"}]},
    {"op": "select", "fields": [{"field": "a"}]},
    {"op": "join", "left": "l", "right": "r", "on": "id", "output_id": "j"},
    {"op": "pivot", "index": "a", "columns": "b", "values": "c"},
    {"op": "check", "expr": "a IS NOT NULL"},
    {"op": "profile"},
    {"op": "extract"},
    {"op": "structure", "provider": "regex", "model": {"fields": [{"name": "n"}]}},
    {"op": "http_lookup", "url": "https://x/{a}", "fields": [{"name": "v", "path": "v"}]},
]


def _pipeline(steps, ptype="viz"):
    return PipelineBase(id="p", name="p", sources=["s"], steps=steps, pipeline_type=ptype)


@pytest.mark.parametrize("step", _EXAMPLES, ids=lambda s: f"{s['op']}-{s.get('mode', '')}")
def test_every_op_round_trips_byte_for_byte(step):
    """Writes validate through the union but store what was sent — no
    defaults injected, so a re-save does not show up as a revision diff."""
    assert _pipeline([step]).model_dump()["steps"] == [step]


def test_examples_cover_every_op():
    assert {s["op"] for s in _EXAMPLES} == STEP_OPS


def test_map_dispatches_on_mode():
    assert isinstance(parse_step(_EXAMPLES[3]), LookupMapStep)
    assert isinstance(parse_step(_EXAMPLES[5]), ExpressionMapStep)
    with pytest.raises(ValidationError):
        _pipeline([{"op": "map", "mode": "nonsense", "output_field": "x", "expr": "1"}])


def test_unknown_op_is_rejected_on_write_and_kept_on_read():
    future = {"op": "from_the_future", "x": 1}
    with pytest.raises(ValidationError):
        _pipeline([future])
    step = parse_step(future)
    assert isinstance(step, UnknownStep)
    assert step.raw == future
    with pytest.raises(CompilerError, match="unknown step op 'from_the_future'"):
        step.compile(None, None)


def test_a_bad_config_for_a_known_op_still_raises_on_read():
    with pytest.raises(ValidationError):
        parse_step({"op": "retype", "field": "a", "to_type": "nonsense"})


def test_openapi_has_a_one_of_for_steps():
    schema = app.openapi()["components"]["schemas"]
    items = schema["PipelineBase"]["properties"]["steps"]["items"]
    refs = {r["$ref"].rsplit("/", 1)[1] for r in items["oneOf"]}
    assert {"FilterStep", "LookupMapStep", "ExpressionMapStep", "HttpLookupStep"} <= refs
    assert len(refs) == len(STEP_OPS) + 1  # map has two classes


def test_allowed_ops_covers_every_pipeline_type():
    assert set(ALLOWED_OPS) == {"transform", "quality", "eval", "viz"}
    assert all(ops <= STEP_OPS for ops in ALLOWED_OPS.values())
    assert ALLOWED_OPS["viz"] == STEP_OPS


@pytest.mark.parametrize("ptype,op", [
    ("quality", "aggregate"), ("quality", "pivot"),
    ("transform", "check"), ("transform", "profile"),
    ("eval", "check"), ("eval", "profile"),
])
def test_validator_enforces_allowed_ops(ptype, op):
    step = next(s for s in _EXAMPLES if s["op"] == op)
    with pytest.raises(ValidationError, match=f"not allowed in {ptype} pipelines"):
        _pipeline([step], ptype)


def test_quality_still_takes_check_and_transform_still_takes_filter():
    _pipeline([{"op": "check", "expr": "a > 0"}], "quality")
    _pipeline([{"op": "filter", "expr": "a > 0"}], "transform")


def test_eval_still_needs_a_structure_step():
    with pytest.raises(ValidationError, match="structure"):
        _pipeline([{"op": "filter", "expr": "a > 0"}], "eval")


def test_allowed_ops_endpoint():
    body = TestClient(app).get("/api/allowed-ops").json()
    assert body == {k: sorted(v) for k, v in ALLOWED_OPS.items()}
