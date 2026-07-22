"""Compiler emits step events via the on_step callback."""
from __future__ import annotations

import ibis
import pandas as pd
import pytest

from dte.compiler.ibis_compiler import compile_pipeline
from dte.errors import CompilerError
from dte.models.pipeline import JsonFileTarget, Pipeline


@pytest.fixture
def con():
    return ibis.duckdb.connect()


@pytest.fixture
def people(con):
    return con.create_table(
        "people",
        pd.DataFrame([{"name": "alice", "age": 30}, {"name": "bob", "age": 17}]),
        overwrite=True,
    )


def _pipeline(steps):
    return Pipeline(id="p", name="p", sources=["src"], steps=steps, output_id="o")


def test_on_step_records_start_and_complete(people):
    events: list[tuple] = []
    compile_pipeline(
        _pipeline([
            {"op": "filter", "expr": "age >= 18"},
            {"op": "rename", "mappings": {"name": "full_name"}},
        ]),
        {"src": people},
        output=JsonFileTarget(type="json_file", path="/tmp/out.json"),
        on_step=lambda i, op, status, msg=None: events.append((i, op, status)),
    )
    assert events == [
        (0, "filter", "started"),
        (0, "filter", "completed"),
        (1, "rename", "started"),
        (1, "rename", "completed"),
    ]


def test_on_step_records_failure(people):
    events: list[tuple] = []
    with pytest.raises(CompilerError):
        compile_pipeline(
            _pipeline([{"op": "retype", "field": "nope", "to_type": "int"}]),
            {"src": people},
            output=JsonFileTarget(type="json_file", path="/tmp/out.json"),
            on_step=lambda i, op, status, msg=None: events.append((i, op, status)),
        )
    assert (0, "retype", "started") in events
    assert (0, "retype", "failed") in events
    assert (0, "retype", "completed") not in events


def test_on_step_callback_errors_do_not_break_compile(people):
    """Telemetry must never crash a run."""
    def _bad(*_a, **_k):
        raise RuntimeError("callback exploded")

    # Should not raise despite the exploding callback.
    compile_pipeline(
        _pipeline([{"op": "filter", "expr": "age >= 18"}]),
        {"src": people},
        output=JsonFileTarget(type="json_file", path="/tmp/out.json"),
        on_step=_bad,
    ).execute()
