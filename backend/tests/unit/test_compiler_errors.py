"""Error-path coverage for the compiler.

Compile-time validation surfaces `CompilerError` (a `DTEUserError`) so the API
can turn it into a 422 without leaking a raw stack trace.
"""
from __future__ import annotations

import ibis
import pandas as pd
import pytest

from dte.compiler.ibis_compiler import compile_pipeline
from dte.errors import CompilerError, DTEUserError
from dte.models.pipeline import JsonFileTarget, Pipeline


@pytest.fixture
def con():
    return ibis.duckdb.connect()


@pytest.fixture
def people(con):
    df = pd.DataFrame([{"name": "alice", "age": 30}])
    return con.create_table("people", df, overwrite=True)


def _pipeline(steps, output_fields=None):
    cfg = {"type": "json_file", "path": "/tmp/out.json"}
    if output_fields:
        cfg["fields"] = output_fields
    return Pipeline(id="p", name="p", sources=["src"], steps=steps, output_id="o"), JsonFileTarget(**cfg)


def _compile(pipeline_and_output, tables, lookups=None):
    p, o = pipeline_and_output
    return compile_pipeline(p, tables, output=o, lookup_tables=lookups or {})


def test_compiler_error_is_a_user_error():
    """API handler branches on DTEUserError → 422."""
    assert issubclass(CompilerError, DTEUserError)


def test_retype_unknown_target_type_rejected_by_model(people):
    """to_type is a Literal on RetypeStep — Pydantic catches it before compile."""
    from pydantic import ValidationError
    p = _pipeline([{"op": "retype", "field": "age", "to_type": "nonesuch"}])
    with pytest.raises(ValidationError):
        _compile(p, {"src": people}).execute()


def test_retype_unknown_field_raises(people):
    p = _pipeline([{"op": "retype", "field": "no_such_col", "to_type": "int"}])
    with pytest.raises(CompilerError, match="unknown field"):
        _compile(p, {"src": people}).execute()


def test_output_field_unknown_column_raises(people):
    p = _pipeline([], output_fields=[{"field": "no_such_col"}])
    with pytest.raises(CompilerError, match="unknown field"):
        _compile(p, {"src": people}).execute()


def test_sort_unknown_field_raises(people):
    p = _pipeline([{"op": "sort", "by": ["no_such_col"]}])
    with pytest.raises(CompilerError, match="unknown field"):
        _compile(p, {"src": people}).execute()


def test_aggregate_unknown_field_raises(people):
    p = _pipeline([{
        "op": "aggregate",
        "group_by": ["name"],
        "aggregations": [{"field": "no_such_col", "func": "sum", "alias": "s"}],
    }])
    with pytest.raises(CompilerError, match="unknown field"):
        _compile(p, {"src": people}).execute()


def test_lookup_missing_lookup_id_raises(people):
    p = _pipeline([{
        "op": "map", "mode": "lookup",
        "field": "name", "lookup_id": "does_not_exist", "output_field": "mapped",
    }])
    with pytest.raises(CompilerError, match="unknown lookup_id"):
        _compile(p, {"src": people}).execute()
