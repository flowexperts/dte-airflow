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


# The old builder menus, now the one rule set (save enforces it).
_EXPECTED = {
    "quality": {"check", "profile", "filter", "rename", "select", "join"},
    "eval": STEP_OPS - {"check", "profile", "aggregate", "pivot"},
    "transform": STEP_OPS - {"check", "profile"},
    "viz": STEP_OPS,
}


def test_allowed_ops_match_the_old_builder_menus():
    assert ALLOWED_OPS == _EXPECTED


_STRUCTURE = next(s for s in _EXAMPLES if s["op"] == "structure")
_DISALLOWED = [(t, op) for t in ("quality", "eval", "transform") for op in sorted(STEP_OPS - _EXPECTED[t])]


@pytest.mark.parametrize("ptype,op", _DISALLOWED)
def test_validator_enforces_allowed_ops(ptype, op):
    step = next(s for s in _EXAMPLES if s["op"] == op)
    extra = [_STRUCTURE] if ptype == "eval" else []
    with pytest.raises(ValidationError, match=f"not allowed in {ptype} pipelines"):
        _pipeline([step, *extra], ptype)


def test_quality_still_takes_check_and_transform_still_takes_filter():
    _pipeline([{"op": "check", "expr": "a > 0"}], "quality")
    _pipeline([{"op": "filter", "expr": "a > 0"}], "transform")


@pytest.mark.parametrize("ptype,op", [("quality", "sort"), ("eval", "aggregate"), ("transform", "check")])
def test_api_save_rejects_a_disallowed_op_with_422(ptype, op):
    step = next(s for s in _EXAMPLES if s["op"] == op)
    steps = [step, _STRUCTURE] if ptype == "eval" else [step]
    body = {"id": "p", "name": "p", "sources": ["s"], "steps": steps,
            "pipeline_type": ptype, "output_id": "o"}
    c = TestClient(app)
    for r in (c.post("/api/pipelines", json=body), c.put("/api/pipelines/p", json=body)):
        assert r.status_code == 422, r.text
        assert f"not allowed in {ptype} pipelines" in r.text


def test_old_revision_with_a_now_disallowed_op_still_loads():
    """Lenient read: rows saved before the rule tightened keep loading and
    compiling; only a re-save hits the rule."""
    import asyncio

    from dte.api.deps import get_pipeline_store
    from dte.models.pipeline import Pipeline
    from tests.fakes import FakePipelineStore

    steps = [{"op": "sort", "by": ["a"]},
             {"op": "aggregate", "group_by": ["a"],
              "aggregations": [{"field": "b", "func": "sum", "alias": "s"}]}]
    store = FakePipelineStore()
    asyncio.get_event_loop().run_until_complete(store.save(Pipeline(
        id="old", name="old", sources=["s"], pipeline_type="quality", steps=steps)))
    app.dependency_overrides[get_pipeline_store] = lambda: store
    try:
        c = TestClient(app)
        assert c.get("/api/pipelines/old").json()["steps"] == steps
        assert c.get("/api/pipelines").status_code == 200
        assert c.get("/api/pipelines/old/schedule").status_code == 200
    finally:
        app.dependency_overrides.pop(get_pipeline_store, None)
    assert [type(parse_step(s)).__name__ for s in steps] == ["SortStep", "AggregateStep"]


def test_eval_still_needs_a_structure_step():
    with pytest.raises(ValidationError, match="structure"):
        _pipeline([{"op": "filter", "expr": "a > 0"}], "eval")


def test_allowed_ops_endpoint():
    body = TestClient(app).get("/api/allowed-ops").json()
    assert body == {k: sorted(v) for k, v in _EXPECTED.items()}
