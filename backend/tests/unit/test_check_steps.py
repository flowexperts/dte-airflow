"""Unit tests for quality check steps (plan 043).

Check steps run during compilation via on_quality_result callback, leaving
the table unchanged. Engine must be supplied for checks to execute.
"""
import pandas as pd
import pytest

import ibis

from dte.compiler.ibis_compiler import compile_pipeline
from dte.engine.duckdb_engine import DuckDBEngine
from dte.models.pipeline import Pipeline, PipelineBase


def _make_quality_pipeline(steps):
    """Build a quality pipeline (no output_id required)."""
    return Pipeline(
        id="qp1",
        name="quality-test",
        sources=["src"],
        steps=steps,
        output_id=None,
        pipeline_type="quality",
    )


def _make_transform_pipeline(steps):
    """Build a transform pipeline with check steps mixed in."""
    return Pipeline(
        id="p1",
        name="transform-test",
        sources=["src"],
        steps=steps,
        output_id="out1",
        pipeline_type="transform",
    )


@pytest.fixture
def engine():
    return DuckDBEngine()


@pytest.fixture
def orders_table(engine):
    df = pd.DataFrame([
        {"order_id": 1, "amount": 10.0, "status": "ok"},
        {"order_id": 2, "amount": 20.0, "status": "ok"},
        {"order_id": 3, "amount": 30.0, "status": "pending"},
    ])
    engine.con.create_table("orders", df, overwrite=True)
    return engine.con.table("orders")


@pytest.fixture
def orders_with_nulls_table(engine):
    df = pd.DataFrame([
        {"order_id": 1, "amount": 10.0, "status": "ok"},
        {"order_id": 2, "amount": None, "status": None},
        {"order_id": 3, "amount": 30.0, "status": "pending"},
    ])
    engine.con.create_table("orders_nulls", df, overwrite=True)
    return engine.con.table("orders_nulls")


@pytest.fixture
def orders_with_dupes_table(engine):
    df = pd.DataFrame([
        {"order_id": 1, "amount": 10.0},
        {"order_id": 1, "amount": 20.0},  # duplicate order_id
        {"order_id": 3, "amount": 30.0},
    ])
    engine.con.create_table("orders_dupes", df, overwrite=True)
    return engine.con.table("orders_dupes")


# ── check_not_null ────────────────────────────────────────────────────────────

def test_check_not_null_pass(engine, orders_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_not_null", "column": "order_id", "severity": "fail"},
    ])
    quality_results = []

    result_table = compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    # Table passes through unchanged
    assert result_table.count().execute() == 3
    # One result, passed
    assert len(quality_results) == 1
    qr = quality_results[0]
    assert qr.passed is True
    assert qr.contract_type == "check_not_null"
    assert qr.severity == "fail"


def test_check_not_null_fail(engine, orders_with_nulls_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_not_null", "column": "amount", "severity": "fail"},
    ])
    quality_results = []

    result_table = compile_pipeline(
        pipeline,
        {"src": orders_with_nulls_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    # Table passes through unchanged
    assert result_table.count().execute() == 3
    # One result, failed
    assert len(quality_results) == 1
    qr = quality_results[0]
    assert qr.passed is False
    assert "1 null" in qr.detail
    assert qr.severity == "fail"


def test_check_not_null_warn_severity(engine, orders_with_nulls_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_not_null", "column": "status", "severity": "warn"},
    ])
    quality_results = []

    compile_pipeline(
        pipeline,
        {"src": orders_with_nulls_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    assert len(quality_results) == 1
    qr = quality_results[0]
    assert qr.passed is False
    assert qr.severity == "warn"


# ── check_unique ─────────────────────────────────────────────────────────────

def test_check_unique_pass(engine, orders_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_unique", "column": "order_id", "severity": "fail"},
    ])
    quality_results = []

    result_table = compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    assert result_table.count().execute() == 3
    assert len(quality_results) == 1
    assert quality_results[0].passed is True


def test_check_unique_fail(engine, orders_with_dupes_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_unique", "column": "order_id", "severity": "fail"},
    ])
    quality_results = []

    compile_pipeline(
        pipeline,
        {"src": orders_with_dupes_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    assert len(quality_results) == 1
    qr = quality_results[0]
    assert qr.passed is False
    assert "duplicate" in qr.detail


# ── check_row_count ──────────────────────────────────────────────────────────

def test_check_row_count_pass(engine, orders_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_row_count", "min": 1, "max": 10, "severity": "fail"},
    ])
    quality_results = []

    result_table = compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    assert result_table.count().execute() == 3
    assert len(quality_results) == 1
    assert quality_results[0].passed is True


def test_check_row_count_fail_too_few(engine, orders_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_row_count", "min": 10, "severity": "fail"},
    ])
    quality_results = []

    compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    assert len(quality_results) == 1
    qr = quality_results[0]
    assert qr.passed is False
    assert "out of range" in qr.detail


def test_check_row_count_fail_too_many(engine, orders_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_row_count", "max": 1, "severity": "warn"},
    ])
    quality_results = []

    compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    assert len(quality_results) == 1
    qr = quality_results[0]
    assert qr.passed is False
    assert qr.severity == "warn"


# ── check_range ──────────────────────────────────────────────────────────────

def test_check_range_pass(engine, orders_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_range", "column": "amount", "min": 5.0, "max": 100.0},
    ])
    quality_results = []

    compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    assert len(quality_results) == 1
    assert quality_results[0].passed is True


def test_check_range_fail(engine, orders_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_range", "column": "amount", "min": 15.0},
    ])
    quality_results = []

    compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    assert len(quality_results) == 1
    qr = quality_results[0]
    assert qr.passed is False
    assert "out of range" in qr.detail


# ── check_accepted_values ────────────────────────────────────────────────────

def test_check_accepted_values_pass(engine, orders_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_accepted_values", "column": "status",
         "values": ["ok", "pending", "failed"]},
    ])
    quality_results = []

    compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    assert quality_results[0].passed is True


def test_check_accepted_values_fail(engine, orders_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_accepted_values", "column": "status", "values": ["ok"]},
    ])
    quality_results = []

    compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    qr = quality_results[0]
    assert qr.passed is False
    assert "not in accepted list" in qr.detail


# ── check_regex ──────────────────────────────────────────────────────────────

def test_check_regex_pass(engine, orders_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_regex", "column": "status", "pattern": "^(ok|pending)$"},
    ])
    quality_results = []

    compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    assert quality_results[0].passed is True


def test_check_regex_fail(engine, orders_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_regex", "column": "status", "pattern": "^ok$"},
    ])
    quality_results = []

    compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    qr = quality_results[0]
    assert qr.passed is False


# ── check_custom_sql ─────────────────────────────────────────────────────────

def test_check_custom_sql_pass(engine, orders_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_custom_sql", "sql": "amount > 0", "label": "positive amounts"},
    ])
    quality_results = []

    compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    assert quality_results[0].passed is True


def test_check_custom_sql_fail(engine, orders_table):
    pipeline = _make_quality_pipeline([
        {"op": "check_custom_sql", "sql": "amount > 100", "label": "large amounts"},
    ])
    quality_results = []

    compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    qr = quality_results[0]
    assert qr.passed is False
    assert "large amounts" in qr.detail


# ── profile ──────────────────────────────────────────────────────────────────

def test_profile_step_pass_through(engine, orders_table):
    """Profile step returns table unchanged and calls callback for each column."""
    pipeline = _make_quality_pipeline([
        {"op": "profile", "columns": ["order_id", "amount"]},
    ])
    quality_results = []

    result_table = compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    # Table passes through unchanged
    assert result_table.count().execute() == 3
    # One result per profiled column
    assert len(quality_results) == 2
    for qr in quality_results:
        assert qr.contract_type == "column_profile"
        assert qr.passed is True


def test_profile_step_all_columns(engine, orders_table):
    """Profile step with empty columns list profiles all columns."""
    pipeline = _make_quality_pipeline([
        {"op": "profile"},  # no columns → profile all
    ])
    quality_results = []

    compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    # orders_table has 3 columns: order_id, amount, status
    assert len(quality_results) == 3


# ── multiple checks in sequence ───────────────────────────────────────────────

def test_multiple_checks_accumulate(engine, orders_table):
    """Multiple check steps each produce a quality result."""
    pipeline = _make_quality_pipeline([
        {"op": "check_not_null", "column": "order_id"},
        {"op": "check_row_count", "min": 1, "max": 100},
        {"op": "check_unique", "column": "order_id"},
    ])
    quality_results = []

    result_table = compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    assert result_table.count().execute() == 3
    assert len(quality_results) == 3
    assert all(qr.passed for qr in quality_results)


# ── pipeline_type validation ──────────────────────────────────────────────────

def test_quality_pipeline_rejects_aggregate():
    """Aggregate step is not allowed in quality pipelines (validated at PipelineBase)."""
    with pytest.raises(Exception, match="not allowed in quality"):
        PipelineBase(
            id="qp2",
            name="bad",
            sources=["src"],
            steps=[
                {"op": "aggregate", "group_by": [], "aggregations": [
                    {"field": "amount", "func": "sum", "alias": "total"}
                ]},
            ],
            output_id=None,
            pipeline_type="quality",
        )


def test_quality_pipeline_rejects_pivot():
    """Pivot step is not allowed in quality pipelines (validated at PipelineBase)."""
    with pytest.raises(Exception, match="not allowed in quality"):
        PipelineBase(
            id="qp3",
            name="bad",
            sources=["src"],
            steps=[
                {"op": "pivot", "index": "a", "columns": "b", "values": "c"},
            ],
            output_id=None,
            pipeline_type="quality",
        )


def test_quality_pipeline_output_id_optional():
    """Quality pipelines don't require output_id."""
    p = PipelineBase(
        id="qp4",
        name="no-dest",
        sources=["src"],
        steps=[{"op": "check_row_count", "min": 1}],
        output_id=None,
        pipeline_type="quality",
    )
    assert p.output_id is None
    assert p.pipeline_type == "quality"


def test_transform_pipeline_still_accepts_check_steps(engine, orders_table):
    """Transform pipelines can include check steps (data passes through)."""
    pipeline = _make_transform_pipeline([
        {"op": "check_not_null", "column": "order_id"},
    ])
    quality_results = []

    result_table = compile_pipeline(
        pipeline,
        {"src": orders_table},
        engine=engine,
        on_quality_result=lambda idx, r: quality_results.append(r),
    )

    assert result_table.count().execute() == 3
    assert len(quality_results) == 1
    assert quality_results[0].passed is True
