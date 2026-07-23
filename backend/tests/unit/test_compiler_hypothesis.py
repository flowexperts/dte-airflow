"""Property-based coverage for the compiler.

The exhaustive per-op tests in `test_compiler.py` catch specific known bugs;
these properties catch *classes* of bugs — anything the compiler emits with a
random-but-valid step sequence must survive execute() without raising, or fail
with a typed `CompilerError` (never a raw `KeyError` / `AttributeError`).
"""
from __future__ import annotations

import ibis
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dte.compiler.ibis_compiler import compile_pipeline
from dte.errors import CompilerError
from dte.models.pipeline import JsonFileTarget, Pipeline


_FIELDS = ["a", "b", "c", "d"]


@pytest.fixture(scope="module")
def base_table():
    con = ibis.duckdb.connect()
    df = pd.DataFrame(
        [
            {"a": 1, "b": "x", "c": 1.0, "d": True},
            {"a": 2, "b": "y", "c": 2.5, "d": False},
            {"a": 3, "b": "z", "c": 3.5, "d": True},
        ]
    )
    return con.create_table("t", df, overwrite=True)


def _rename_step(draw):
    # User-facing shape is `{old: new}`; the compiler flips to ibis's
    # `{new: old}` form. Pick `old` from real columns so we don't accidentally
    # exercise "rename an unknown source" — that's a compiler-validation gap
    # tracked separately, not a property this test protects.
    old = draw(st.sampled_from(_FIELDS))
    new = draw(st.text(alphabet="abcdefghij_", min_size=1, max_size=5))
    return {"op": "rename", "mappings": {old: new}}


def _select_step(draw):
    fields = draw(st.lists(st.sampled_from(_FIELDS), min_size=1, max_size=3, unique=True))
    return {"op": "select", "fields": [{"field": f} for f in fields]}


def _sort_step(draw):
    return {"op": "sort", "by": [draw(st.sampled_from(_FIELDS))]}


@st.composite
def _step(draw):
    kind = draw(st.sampled_from(["rename", "select", "sort"]))
    if kind == "rename":
        return _rename_step(draw)
    if kind == "select":
        return _select_step(draw)
    return _sort_step(draw)


@st.composite
def _steps(draw):
    return draw(st.lists(_step(), min_size=0, max_size=4))


@given(steps=_steps())
@settings(
    max_examples=40,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_random_valid_pipeline_never_raises_unhandled(steps, base_table):
    """A random compose of rename/select/sort either succeeds or raises
    `CompilerError`. Anything else is a compiler bug."""
    pipeline = Pipeline(
        id="p", name="p", sources=["src"], steps=steps, output_id="o",
    )
    try:
        result = compile_pipeline(
            pipeline,
            {"src": base_table},
            output=JsonFileTarget(type="json_file", path="/tmp/out.json"),
        )
        result.execute()
    except CompilerError:
        return  # expected — typed compile-time rejection
    except Exception as e:
        pytest.fail(f"compiler leaked untyped exception {type(e).__name__}: {e}")
