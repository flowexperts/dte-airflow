import pytest
import ibis
import pandas as pd
from dte.compiler.ibis_compiler import compile_pipeline
from dte.models.pipeline import Pipeline


def make_pipeline(steps, output_fields=None):
    output = {"type": "json_file", "path": "/tmp/out.json"}
    if output_fields:
        output["fields"] = output_fields
    return Pipeline(
        id="p1", name="test",
        sources=[{"id": "src", "type": "json_file", "path": "/dummy.json"}],
        steps=steps,
        output=output,
    )


@pytest.fixture
def con():
    return ibis.duckdb.connect()


@pytest.fixture
def people_table(con):
    df = pd.DataFrame([
        {"name": "alice", "age": 30, "score": 9.5},
        {"name": "bob", "age": 17, "score": 6.0},
        {"name": "carol", "age": 25, "score": 8.5},
    ])
    return con.create_table("people", df, overwrite=True)


@pytest.fixture
def sales_table(con):
    df = pd.DataFrame([
        {"product": "A", "category": "x", "price": 10.0, "quantity": 3},
        {"product": "B", "category": "x", "price": 20.0, "quantity": 1},
        {"product": "C", "category": "y", "price": 15.0, "quantity": 2},
    ])
    return con.create_table("sales", df, overwrite=True)


@pytest.fixture
def country_table(con):
    df = pd.DataFrame([
        {"code": "US", "country_code": "US"},
        {"code": "CA", "country_code": "CA"},
        {"code": "GB", "country_code": "GB"},
    ])
    return con.create_table("countries", df, overwrite=True)


def test_filter_step(people_table):
    pipeline = make_pipeline([{"op": "filter", "expr": "age >= 18"}])
    result = compile_pipeline(pipeline, {"src": people_table})
    df = result.execute()
    assert len(df) == 2
    assert set(df["name"].tolist()) == {"alice", "carol"}


def test_rename_step(people_table):
    pipeline = make_pipeline([{"op": "rename", "mappings": {"name": "full_name"}}])
    result = compile_pipeline(pipeline, {"src": people_table})
    df = result.execute()
    assert "full_name" in df.columns
    assert "name" not in df.columns


def test_retype_step(con):
    df = pd.DataFrame([{"age_str": "30"}, {"age_str": "25"}])
    table = con.create_table("retype_test", df, overwrite=True)
    pipeline = make_pipeline([{"op": "retype", "field": "age_str", "to_type": "int"}])
    result = compile_pipeline(pipeline, {"src": table})
    df_out = result.execute()
    assert df_out["age_str"].dtype in (int, "int64", "Int64") or str(df_out["age_str"].dtype).startswith("int")


def test_lookup_map_step(country_table):
    pipeline = make_pipeline([{
        "op": "map", "mode": "lookup", "field": "country_code",
        "table": {"US": "United States", "CA": "Canada"},
        "default": "Unknown"
    }])
    result = compile_pipeline(pipeline, {"src": country_table})
    df = result.execute()
    assert "United States" in df["country_code"].tolist()
    assert "Canada" in df["country_code"].tolist()
    assert "Unknown" in df["country_code"].tolist()


def test_expression_map_step(sales_table):
    pipeline = make_pipeline([{
        "op": "map", "mode": "expression",
        "output_field": "total", "expr": "price * quantity"
    }])
    result = compile_pipeline(pipeline, {"src": sales_table})
    df = result.execute()
    assert "total" in df.columns
    assert df[df["product"] == "A"]["total"].iloc[0] == pytest.approx(30.0)


def test_sort_step_ascending(people_table):
    pipeline = make_pipeline([{"op": "sort", "by": ["age"], "ascending": True}])
    result = compile_pipeline(pipeline, {"src": people_table})
    df = result.execute()
    ages = df["age"].tolist()
    assert ages == sorted(ages)


def test_sort_step_descending(people_table):
    pipeline = make_pipeline([{"op": "sort", "by": ["age"], "ascending": False}])
    result = compile_pipeline(pipeline, {"src": people_table})
    df = result.execute()
    ages = df["age"].tolist()
    assert ages == sorted(ages, reverse=True)


def test_aggregate_sum(sales_table):
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": ["category"],
        "aggregations": [{"field": "price", "func": "sum", "alias": "total_price"}]
    }])
    result = compile_pipeline(pipeline, {"src": sales_table})
    df = result.execute()
    x_row = df[df["category"] == "x"]
    assert x_row["total_price"].iloc[0] == pytest.approx(30.0)


def test_aggregate_count(sales_table):
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": ["category"],
        "aggregations": [{"field": "product", "func": "count", "alias": "cnt"}]
    }])
    result = compile_pipeline(pipeline, {"src": sales_table})
    df = result.execute()
    x_row = df[df["category"] == "x"]
    assert x_row["cnt"].iloc[0] == 2


def test_output_field_selection(people_table):
    pipeline = make_pipeline(
        steps=[],
        output_fields=[{"field": "name"}, {"field": "age"}]
    )
    result = compile_pipeline(pipeline, {"src": people_table})
    df = result.execute()
    assert set(df.columns) == {"name", "age"}
    assert "score" not in df.columns


def test_output_field_alias(people_table):
    pipeline = make_pipeline(
        steps=[],
        output_fields=[{"field": "name", "alias": "full_name"}, {"field": "age"}]
    )
    result = compile_pipeline(pipeline, {"src": people_table})
    df = result.execute()
    assert "full_name" in df.columns
    assert "name" not in df.columns
