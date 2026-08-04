"""Tests for the unified check step (filter-like assertion)."""
import pytest
import ibis
from dte.models.pipeline import Pipeline, PipelineBase, CheckStep
from dte.engine.duckdb_engine import DuckDBEngine
from dte.compiler.ibis_compiler import compile_pipeline


def _engine_and_table(rows: list[dict]):
    import pandas as pd
    engine = DuckDBEngine()
    df = pd.DataFrame(rows)
    engine.con.create_table("_test_tbl", df, overwrite=True)
    t = engine.con.table("_test_tbl")
    return engine, t


def _compile_check(rows, expr, severity="fail", label=""):
    engine, t = _engine_and_table(rows)
    quality_results = []
    pipeline = Pipeline(
        id="p1", name="p1",
        sources=["default"],
        steps=[{"op": "check", "expr": expr, "severity": severity, "label": label}],
        pipeline_type="quality",
    )
    compile_pipeline(pipeline, {"default": t}, engine=engine,
                     on_quality_result=lambda idx, r: quality_results.append(r))
    return quality_results


def test_check_pass_all_rows_match():
    results = _compile_check([{"age": 25}, {"age": 30}], "age > 18")
    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].detail is None


def test_check_fail_some_rows_violate():
    results = _compile_check([{"age": 25}, {"age": 10}], "age > 18")
    assert len(results) == 1
    assert results[0].passed is False
    assert "1/2 rows failed" in results[0].detail


def test_check_fail_all_rows_violate():
    results = _compile_check([{"age": 5}, {"age": 10}], "age > 18")
    assert results[0].passed is False
    assert "2/2 rows failed" in results[0].detail


def test_check_severity_propagated():
    results = _compile_check([{"age": 5}], "age > 18", severity="warn")
    assert results[0].severity == "warn"
    assert results[0].passed is False


def test_check_severity_fail_default():
    results = _compile_check([{"age": 5}], "age > 18")
    assert results[0].severity == "fail"


def test_check_label_in_detail():
    results = _compile_check([{"age": 5}], "age > 18", label="age must be adult")
    assert "age must be adult" in results[0].detail


def test_check_label_defaults_to_expr():
    results = _compile_check([{"age": 5}], "age > 18")
    assert "age > 18" in results[0].detail


def test_check_null_assertion():
    results = _compile_check(
        [{"name": "Alice"}, {"name": None}],
        '"name" IS NOT NULL'
    )
    assert results[0].passed is False
    assert "1/2" in results[0].detail


def test_check_null_passes_when_no_nulls():
    results = _compile_check(
        [{"name": "Alice"}, {"name": "Bob"}],
        '"name" IS NOT NULL'
    )
    assert results[0].passed is True


def test_check_returns_table_unchanged():
    engine, t = _engine_and_table([{"x": 1}, {"x": 2}, {"x": 3}])
    pipeline = Pipeline(
        id="p1", name="p1",
        sources=["default"], steps=[{"op": "check", "expr": "x > 0"}],
        pipeline_type="quality",
    )
    result_table = compile_pipeline(pipeline, {"default": t}, engine=engine)
    rows = result_table.execute()
    assert len(rows) == 3  # unchanged


def test_multiple_checks_accumulate():
    engine = DuckDBEngine()
    engine.con.con.execute(
        "CREATE OR REPLACE TABLE _test_multi (x INTEGER, name VARCHAR); "
        "INSERT INTO _test_multi VALUES (-1, NULL)"
    )
    t = engine.con.table("_test_multi")
    quality_results = []
    pipeline = Pipeline(
        id="p1", name="p1",
        sources=["default"],
        steps=[
            {"op": "check", "expr": "x > 0", "label": "x positive"},
            {"op": "check", "expr": '"name" IS NOT NULL', "label": "name not null"},
        ],
        pipeline_type="quality",
    )
    compile_pipeline(pipeline, {"default": t}, engine=engine,
                     on_quality_result=lambda idx, r: quality_results.append(r))
    assert len(quality_results) == 2
    assert all(not r.passed for r in quality_results)


def test_quality_pipeline_rejects_aggregate():
    with pytest.raises(ValueError, match="aggregate"):
        PipelineBase(
            id="p1", name="p1", sources=[],
            pipeline_type="quality",
            steps=[{"op": "aggregate", "group_by": ["x"], "aggregations": []}],
        )


def test_quality_pipeline_rejects_pivot():
    with pytest.raises(ValueError, match="pivot"):
        PipelineBase(
            id="p1", name="p1", sources=[],
            pipeline_type="quality",
            steps=[{"op": "pivot", "index": "x", "columns": "y", "values": "z"}],
        )


def test_quality_pipeline_output_id_optional():
    p = PipelineBase(id="p1", name="p1", sources=[], steps=[], pipeline_type="quality")
    assert p.output_id is None


def test_check_step_model_validation():
    step = CheckStep(op="check", expr="x > 0", severity="warn", label="positive x")
    assert step.severity == "warn"
    assert step.label == "positive x"


def test_check_step_empty_expr_raises():
    with pytest.raises(ValueError):
        CheckStep(op="check", expr="   ")
