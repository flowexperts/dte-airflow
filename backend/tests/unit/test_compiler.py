import pytest
import ibis
import pandas as pd
from dte.compiler.ibis_compiler import compile_pipeline
from dte.models.pipeline import Pipeline, JoinStep, PivotStep


def make_pipeline(steps, output_fields=None):
    output = {"type": "json_file", "path": "/tmp/out.json"}
    if output_fields:
        output["fields"] = output_fields
    return Pipeline(
        id="p1", name="test",
        sources=[{
            "id": "src",
            "source_type": "filesystem",
            "config": {"bucket_url": "/tmp"},
            "table": "dummy",
        }],
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


def test_select_step_keeps_only_listed_fields(people_table):
    pipeline = make_pipeline([
        {"op": "select", "fields": [{"field": "name"}, {"field": "age"}]}
    ])
    result = compile_pipeline(pipeline, {"src": people_table})
    df = result.execute()
    assert set(df.columns) == {"name", "age"}


def test_select_step_supports_alias(people_table):
    pipeline = make_pipeline([
        {"op": "select", "fields": [{"field": "name", "alias": "full_name"}]}
    ])
    result = compile_pipeline(pipeline, {"src": people_table})
    df = result.execute()
    assert "full_name" in df.columns
    assert "name" not in df.columns


def test_select_step_drop_only_keeps_remaining_columns(people_table):
    pipeline = make_pipeline([
        {"op": "select", "drop": ["score"]}
    ])
    result = compile_pipeline(pipeline, {"src": people_table})
    df = result.execute()
    assert set(df.columns) == {"name", "age"}


def test_select_step_composes_with_later_steps(people_table):
    pipeline = make_pipeline([
        {"op": "select", "fields": [{"field": "name"}, {"field": "age"}]},
        {"op": "filter", "expr": "age >= 18"},
    ])
    result = compile_pipeline(pipeline, {"src": people_table})
    df = result.execute()
    assert set(df.columns) == {"name", "age"}
    assert (df["age"] >= 18).all()


def make_join_pipeline(steps, sources, output_fields=None):
    output = {"type": "json_file", "path": "/tmp/out.json"}
    if output_fields:
        output["fields"] = output_fields
    return Pipeline(
        id="p1", name="test",
        sources=sources,
        steps=steps,
        output=output,
    )


@pytest.fixture
def users_table(con):
    df = pd.DataFrame([
        {"id": 1, "name": "alice"},
        {"id": 2, "name": "bob"},
        {"id": 3, "name": "carol"},
    ])
    return con.create_table("users", df, overwrite=True)


@pytest.fixture
def orders_table(con):
    df = pd.DataFrame([
        {"id": 1, "amount": 100},
        {"id": 2, "amount": 200},
        {"id": 4, "amount": 50},
    ])
    return con.create_table("orders", df, overwrite=True)


@pytest.fixture
def regional_orders_table(con):
    df = pd.DataFrame([
        {"id": 1, "region": "east", "amount": 100},
        {"id": 2, "region": "west", "amount": 200},
    ])
    return con.create_table("regional_orders", df, overwrite=True)


@pytest.fixture
def regional_users_table(con):
    df = pd.DataFrame([
        {"id": 1, "region": "east", "name": "alice"},
        {"id": 2, "region": "west", "name": "bob"},
        {"id": 3, "region": "east", "name": "carol"},
    ])
    return con.create_table("regional_users", df, overwrite=True)


def _src(src_id):
    return {
        "id": src_id,
        "source_type": "filesystem",
        "config": {"bucket_url": "/tmp"},
        "table": "dummy",
    }


def test_join_inner(users_table, orders_table):
    pipeline = make_join_pipeline(
        sources=[_src("users"), _src("orders")],
        steps=[{
            "op": "join",
            "left": "users",
            "right": "orders",
            "on": "id",
            "how": "inner",
            "output_id": "joined",
        }],
    )
    result = compile_pipeline(pipeline, {"users": users_table, "orders": orders_table})
    df = result.execute()
    assert len(df) == 2
    assert "name" in df.columns
    assert "amount" in df.columns


def test_join_left(users_table, orders_table):
    pipeline = make_join_pipeline(
        sources=[_src("users"), _src("orders")],
        steps=[{
            "op": "join",
            "left": "users",
            "right": "orders",
            "on": "id",
            "how": "left",
            "output_id": "joined",
        }],
    )
    result = compile_pipeline(pipeline, {"users": users_table, "orders": orders_table})
    df = result.execute()
    assert len(df) == 3
    carol_row = df[df["name"] == "carol"]
    assert carol_row["amount"].isna().all()


def test_join_on_multiple_columns(regional_users_table, regional_orders_table):
    pipeline = make_join_pipeline(
        sources=[_src("regional_users"), _src("regional_orders")],
        steps=[{
            "op": "join",
            "left": "regional_users",
            "right": "regional_orders",
            "on": ["id", "region"],
            "how": "inner",
            "output_id": "joined",
        }],
    )
    result = compile_pipeline(pipeline, {
        "regional_users": regional_users_table,
        "regional_orders": regional_orders_table,
    })
    df = result.execute()
    assert len(df) == 2
    assert "name" in df.columns
    assert "amount" in df.columns


def test_join_result_available_for_next_step(users_table, orders_table):
    pipeline = make_join_pipeline(
        sources=[_src("users"), _src("orders")],
        steps=[
            {
                "op": "join",
                "left": "users",
                "right": "orders",
                "on": "id",
                "how": "inner",
                "output_id": "joined",
            },
            {"op": "filter", "expr": "amount > 100"},
        ],
    )
    result = compile_pipeline(pipeline, {"users": users_table, "orders": orders_table})
    df = result.execute()
    assert len(df) == 1
    assert df["name"].iloc[0] == "bob"


@pytest.fixture
def pivot_sales_table(con):
    df = pd.DataFrame([
        {"region": "East", "product": "A", "sales": 100},
        {"region": "East", "product": "B", "sales": 150},
        {"region": "West", "product": "A", "sales": 200},
        {"region": "West", "product": "B", "sales": 50},
    ])
    return con.create_table("pivot_sales", df, overwrite=True)


def test_pivot_sum(pivot_sales_table):
    pipeline = make_pipeline([{
        "op": "pivot",
        "index": "region",
        "columns": "product",
        "values": "sales",
        "agg": "sum",
    }])
    result = compile_pipeline(pipeline, {"src": pivot_sales_table})
    df = result.execute()
    assert "A" in df.columns
    assert "B" in df.columns
    east_row = df[df["region"] == "East"]
    assert east_row["A"].iloc[0] == 100
    assert east_row["B"].iloc[0] == 150


def test_pivot_count(pivot_sales_table):
    pipeline = make_pipeline([{
        "op": "pivot",
        "index": "region",
        "columns": "product",
        "values": "sales",
        "agg": "count",
    }])
    result = compile_pipeline(pipeline, {"src": pivot_sales_table})
    df = result.execute()
    assert "A" in df.columns
    assert "B" in df.columns
    east_row = df[df["region"] == "East"]
    assert east_row["A"].iloc[0] == 1
    assert east_row["B"].iloc[0] == 1


@pytest.fixture
def struct_orders_table(con):
    """A DuckDB view with a STRUCT column (mimics DuckDB read_json_auto)."""
    con.con.execute("""
        CREATE OR REPLACE VIEW struct_orders AS SELECT * FROM (VALUES
            ('o1', {'amount': 100, 'currency': 'USD'}, {'city': 'NYC'}),
            ('o2', {'amount': 42,  'currency': 'EUR'}, {'city': 'Berlin'}),
            ('o3', {'amount': 250, 'currency': 'USD'}, {'city': 'Austin'})
        ) AS t(id, "order", addr)
    """)
    return con.table("struct_orders")


def test_output_fields_resolve_struct_paths(struct_orders_table):
    pipeline = make_pipeline(
        steps=[],
        output_fields=[
            {"field": "id"},
            {"field": "order.amount", "alias": "amount"},
            {"field": "addr.city"},
        ],
    )
    result = compile_pipeline(pipeline, {"src": struct_orders_table})
    df = result.execute()
    assert set(df.columns) == {"id", "amount", "city"}
    assert sorted(df["amount"].tolist()) == [42, 100, 250]
    assert sorted(df["city"].tolist()) == ["Austin", "Berlin", "NYC"]


def test_select_step_resolves_struct_paths(struct_orders_table):
    pipeline = make_pipeline(
        steps=[{
            "op": "select",
            "fields": [
                {"field": "id"},
                {"field": "order.currency", "alias": "cur"},
            ],
        }],
    )
    result = compile_pipeline(pipeline, {"src": struct_orders_table})
    df = result.execute()
    assert set(df.columns) == {"id", "cur"}
    assert sorted(df["cur"].tolist()) == ["EUR", "USD", "USD"]
