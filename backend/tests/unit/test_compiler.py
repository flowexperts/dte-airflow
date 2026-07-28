import pytest
import ibis
import pandas as pd
from dte.compiler.ibis_compiler import compile_pipeline
from dte.models.pipeline import Pipeline, JoinStep, PivotStep, JsonFileTarget, LookupTable


def _output(output_fields=None):
    cfg = {"type": "json_file", "path": "/tmp/out.json"}
    if output_fields:
        cfg["fields"] = output_fields
    return JsonFileTarget(**cfg)


def make_pipeline(steps, output_fields=None):
    return (
        Pipeline(id="p1", name="test", sources=["src"], steps=steps, output_id="out1"),
        _output(output_fields),
    )


def _run(pipeline_and_output, tables, lookup_tables=None):
    pipeline, output = pipeline_and_output
    return compile_pipeline(
        pipeline, tables, output=output, lookup_tables=lookup_tables or {},
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
def dated_sales_table(con):
    df = pd.DataFrame([
        {"amount": 10.0, "ordered_at": pd.Timestamp("2024-01-05 09:00:00")},
        {"amount": 20.0, "ordered_at": pd.Timestamp("2024-01-20 15:30:00")},
        {"amount": 30.0, "ordered_at": pd.Timestamp("2024-02-10 12:00:00")},
        {"amount": 40.0, "ordered_at": pd.Timestamp("2024-04-01 08:15:00")},
        {"amount": 50.0, "ordered_at": pd.Timestamp("2024-04-02 16:45:00")},
        {"amount": 60.0, "ordered_at": pd.Timestamp("2025-01-01 00:00:00")},
    ])
    return con.create_table("dated_sales", df, overwrite=True)


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
    result = _run(pipeline, {"src": people_table})
    df = result.execute()
    assert len(df) == 2
    assert set(df["name"].tolist()) == {"alice", "carol"}


def test_rename_step(people_table):
    pipeline = make_pipeline([{"op": "rename", "mappings": {"name": "full_name"}}])
    result = _run(pipeline, {"src": people_table})
    df = result.execute()
    assert "full_name" in df.columns
    assert "name" not in df.columns


def test_retype_step(con):
    df = pd.DataFrame([{"age_str": "30"}, {"age_str": "25"}])
    table = con.create_table("retype_test", df, overwrite=True)
    pipeline = make_pipeline([{"op": "retype", "field": "age_str", "to_type": "int"}])
    result = _run(pipeline, {"src": table})
    df_out = result.execute()
    assert df_out["age_str"].dtype in (int, "int64", "Int64") or str(df_out["age_str"].dtype).startswith("int")


def test_lookup_map_step(country_table):
    pipeline = make_pipeline([{
        "op": "map", "mode": "lookup", "field": "country_code",
        "lookup_id": "country_names",
    }])
    lookups = {
        "country_names": LookupTable(
            id="country_names",
            mappings={"US": "United States", "CA": "Canada"},
            default="Unknown",
        ),
    }
    result = _run(pipeline, {"src": country_table}, lookup_tables=lookups)
    df = result.execute()
    assert "United States" in df["country_code"].tolist()
    assert "Canada" in df["country_code"].tolist()
    assert "Unknown" in df["country_code"].tolist()


def test_lookup_map_step_with_output_field(country_table):
    pipeline = make_pipeline([{
        "op": "map", "mode": "lookup", "field": "country_code",
        "lookup_id": "country_names", "output_field": "country_name",
    }])
    lookups = {
        "country_names": LookupTable(
            id="country_names",
            mappings={"US": "United States"},
            default=None,
        ),
    }
    result = _run(pipeline, {"src": country_table}, lookup_tables=lookups)
    df = result.execute()
    assert "country_name" in df.columns
    # original column stays untouched
    assert "country_code" in df.columns


def test_lookup_map_step_missing_lookup_raises(country_table):
    pipeline = make_pipeline([{
        "op": "map", "mode": "lookup", "field": "country_code",
        "lookup_id": "not_registered",
    }])
    from dte.errors import CompilerError
    with pytest.raises(CompilerError, match="unknown lookup_id"):
        _run(pipeline, {"src": country_table})


def test_expression_map_step(sales_table):
    pipeline = make_pipeline([{
        "op": "map", "mode": "expression",
        "output_field": "total", "expr": "price * quantity"
    }])
    result = _run(pipeline, {"src": sales_table})
    df = result.execute()
    assert "total" in df.columns
    assert df[df["product"] == "A"]["total"].iloc[0] == pytest.approx(30.0)


def test_sort_step_ascending(people_table):
    pipeline = make_pipeline([{"op": "sort", "by": ["age"], "ascending": True}])
    result = _run(pipeline, {"src": people_table})
    df = result.execute()
    ages = df["age"].tolist()
    assert ages == sorted(ages)


def test_sort_step_descending(people_table):
    pipeline = make_pipeline([{"op": "sort", "by": ["age"], "ascending": False}])
    result = _run(pipeline, {"src": people_table})
    df = result.execute()
    ages = df["age"].tolist()
    assert ages == sorted(ages, reverse=True)


def test_aggregate_sum(sales_table):
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": ["category"],
        "aggregations": [{"field": "price", "func": "sum", "alias": "total_price"}]
    }])
    result = _run(pipeline, {"src": sales_table})
    df = result.execute()
    x_row = df[df["category"] == "x"]
    assert x_row["total_price"].iloc[0] == pytest.approx(30.0)


def test_aggregate_count(sales_table):
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": ["category"],
        "aggregations": [{"field": "product", "func": "count", "alias": "cnt"}]
    }])
    result = _run(pipeline, {"src": sales_table})
    df = result.execute()
    x_row = df[df["category"] == "x"]
    assert x_row["cnt"].iloc[0] == 2


def test_aggregate_by_date_part_year(dated_sales_table):
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": [{"field": "ordered_at", "part": "year"}],
        "aggregations": [{"field": "amount", "func": "sum", "alias": "total"}],
    }])
    df = _run(pipeline, {"src": dated_sales_table}).execute()
    by_year = {int(r["ordered_at_year"]): float(r["total"]) for _, r in df.iterrows()}
    assert by_year == {2024: pytest.approx(150.0), 2025: pytest.approx(60.0)}


def test_aggregate_by_date_part_month(dated_sales_table):
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": [{"field": "ordered_at", "part": "month"}],
        "aggregations": [{"field": "amount", "func": "sum", "alias": "total"}],
    }])
    df = _run(pipeline, {"src": dated_sales_table}).execute()
    by_month = {int(r["ordered_at_month"]): float(r["total"]) for _, r in df.iterrows()}
    # Jan (2024+2025): 10+20+60=90; Feb: 30; Apr: 40+50=90
    assert by_month == {1: pytest.approx(90.0), 2: pytest.approx(30.0), 4: pytest.approx(90.0)}


def test_aggregate_by_date_part_day(dated_sales_table):
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": [{"field": "ordered_at", "part": "day"}],
        "aggregations": [{"field": "amount", "func": "count", "alias": "n"}],
    }])
    df = _run(pipeline, {"src": dated_sales_table}).execute()
    assert "ordered_at_day" in df.columns


def test_aggregate_by_date_part_hour(dated_sales_table):
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": [{"field": "ordered_at", "part": "hour"}],
        "aggregations": [{"field": "amount", "func": "count", "alias": "n"}],
    }])
    df = _run(pipeline, {"src": dated_sales_table}).execute()
    hours = set(int(h) for h in df["ordered_at_hour"].tolist())
    assert hours == {0, 8, 9, 12, 15, 16}


def test_aggregate_by_date_part_quarter(dated_sales_table):
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": [{"field": "ordered_at", "part": "quarter"}],
        "aggregations": [{"field": "amount", "func": "sum", "alias": "total"}],
    }])
    df = _run(pipeline, {"src": dated_sales_table}).execute()
    assert "ordered_at_quarter" in df.columns


def test_aggregate_by_date_part_week(dated_sales_table):
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": [{"field": "ordered_at", "part": "week"}],
        "aggregations": [{"field": "amount", "func": "count", "alias": "n"}],
    }])
    df = _run(pipeline, {"src": dated_sales_table}).execute()
    assert "ordered_at_week" in df.columns


def test_aggregate_by_date_part_dow(dated_sales_table):
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": [{"field": "ordered_at", "part": "dow"}],
        "aggregations": [{"field": "amount", "func": "count", "alias": "n"}],
    }])
    df = _run(pipeline, {"src": dated_sales_table}).execute()
    assert "ordered_at_dow" in df.columns


def test_aggregate_by_date_part_date(dated_sales_table):
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": [{"field": "ordered_at", "part": "date"}],
        "aggregations": [{"field": "amount", "func": "sum", "alias": "total"}],
    }])
    df = _run(pipeline, {"src": dated_sales_table}).execute()
    assert "ordered_at_date" in df.columns
    # 6 distinct dates
    assert len(df) == 6


def test_aggregate_by_date_part_alias(dated_sales_table):
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": [{"field": "ordered_at", "part": "year", "alias": "yr"}],
        "aggregations": [{"field": "amount", "func": "sum", "alias": "total"}],
    }])
    df = _run(pipeline, {"src": dated_sales_table}).execute()
    assert "yr" in df.columns


def test_aggregate_by_date_part_on_non_temporal_field_raises(sales_table):
    from dte.errors import CompilerError
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": [{"field": "category", "part": "year"}],
        "aggregations": [{"field": "price", "func": "sum", "alias": "total"}],
    }])
    with pytest.raises(CompilerError, match="date/timestamp"):
        _run(pipeline, {"src": sales_table})


def test_aggregate_plain_string_group_by_still_works(sales_table):
    """Backwards compat: plain string entries in group_by continue to work."""
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": ["category"],
        "aggregations": [{"field": "price", "func": "sum", "alias": "total"}],
    }])
    df = _run(pipeline, {"src": sales_table}).execute()
    assert set(df["category"].tolist()) == {"x", "y"}


def test_aggregate_mixed_group_by(dated_sales_table, con):
    """Mix a plain string entry and a date-part entry in the same group_by."""
    df = pd.DataFrame([
        {"cat": "A", "amount": 10.0, "ordered_at": pd.Timestamp("2024-01-05")},
        {"cat": "A", "amount": 20.0, "ordered_at": pd.Timestamp("2024-01-06")},
        {"cat": "B", "amount": 30.0, "ordered_at": pd.Timestamp("2024-02-01")},
    ])
    table = con.create_table("mixed_sales", df, overwrite=True)
    pipeline = make_pipeline([{
        "op": "aggregate",
        "group_by": ["cat", {"field": "ordered_at", "part": "month"}],
        "aggregations": [{"field": "amount", "func": "sum", "alias": "total"}],
    }])
    out = _run(pipeline, {"src": table}).execute()
    assert "cat" in out.columns
    assert "ordered_at_month" in out.columns


def test_output_field_selection(people_table):
    pipeline = make_pipeline(
        steps=[],
        output_fields=[{"field": "name"}, {"field": "age"}]
    )
    result = _run(pipeline, {"src": people_table})
    df = result.execute()
    assert set(df.columns) == {"name", "age"}
    assert "score" not in df.columns


def test_output_field_alias(people_table):
    pipeline = make_pipeline(
        steps=[],
        output_fields=[{"field": "name", "alias": "full_name"}, {"field": "age"}]
    )
    result = _run(pipeline, {"src": people_table})
    df = result.execute()
    assert "full_name" in df.columns
    assert "name" not in df.columns


def test_select_step_keeps_only_listed_fields(people_table):
    pipeline = make_pipeline([
        {"op": "select", "fields": [{"field": "name"}, {"field": "age"}]}
    ])
    result = _run(pipeline, {"src": people_table})
    df = result.execute()
    assert set(df.columns) == {"name", "age"}


def test_select_step_supports_alias(people_table):
    pipeline = make_pipeline([
        {"op": "select", "fields": [{"field": "name", "alias": "full_name"}]}
    ])
    result = _run(pipeline, {"src": people_table})
    df = result.execute()
    assert "full_name" in df.columns
    assert "name" not in df.columns


def test_select_step_drop_only_keeps_remaining_columns(people_table):
    pipeline = make_pipeline([
        {"op": "select", "drop": ["score"]}
    ])
    result = _run(pipeline, {"src": people_table})
    df = result.execute()
    assert set(df.columns) == {"name", "age"}


def test_select_step_drop_on_view_backed_table(con):
    """Regression: ibis.drop() compiles to SELECT * which resolves to the
    underlying view at execution time, re-including dropped columns.
    The compiler must use explicit column selection instead.
    """
    import pandas as pd
    df = pd.DataFrame([
        {"id": 1, "name": "alice", "ssn": "111", "email": "a@x"},
        {"id": 2, "name": "bob", "ssn": "222", "email": "b@x"},
    ])
    # Create a view (not a table) to reproduce the bug path.
    base = con.create_table("_drop_test_base", df, overwrite=True)
    view = con.create_view("_drop_test_view", base, overwrite=True)

    pipeline = make_pipeline([{"op": "select", "drop": ["ssn"]}])
    result = _run(pipeline, {"src": view})
    out_df = result.execute()
    assert "ssn" not in out_df.columns
    assert set(out_df.columns) >= {"id", "name", "email"}


def test_select_step_drop_unknown_column_is_noop(people_table):
    """Dropping a column that doesn't exist in the table is silently ignored."""
    pipeline = make_pipeline([
        {"op": "select", "drop": ["nonexistent_column"]}
    ])
    result = _run(pipeline, {"src": people_table})
    df = result.execute()
    # All original columns remain; the unknown drop target was ignored.
    assert set(df.columns) == {"name", "age", "score"}


def test_select_step_drop_empty_list_is_disallowed():
    """SelectStep requires either fields or drop — empty drop raises at model level."""
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError, match="one of `fields` or `drop` is required"):
        from dte.models.pipeline import SelectStep
        SelectStep(op="select", drop=[])


def test_select_step_composes_with_later_steps(people_table):
    pipeline = make_pipeline([
        {"op": "select", "fields": [{"field": "name"}, {"field": "age"}]},
        {"op": "filter", "expr": "age >= 18"},
    ])
    result = _run(pipeline, {"src": people_table})
    df = result.execute()
    assert set(df.columns) == {"name", "age"}
    assert (df["age"] >= 18).all()


def make_join_pipeline(steps, sources, output_fields=None):
    source_ids = [s["id"] if isinstance(s, dict) else s for s in sources]
    return (
        Pipeline(id="p1", name="test", sources=source_ids, steps=steps, output_id="out1"),
        _output(output_fields),
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
    result = _run(pipeline, {"users": users_table, "orders": orders_table})
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
    result = _run(pipeline, {"users": users_table, "orders": orders_table})
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
    result = _run(pipeline, {
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
    result = _run(pipeline, {"users": users_table, "orders": orders_table})
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
    result = _run(pipeline, {"src": pivot_sales_table})
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
    result = _run(pipeline, {"src": pivot_sales_table})
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
    result = _run(pipeline, {"src": struct_orders_table})
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
    result = _run(pipeline, {"src": struct_orders_table})
    df = result.execute()
    assert set(df.columns) == {"id", "cur"}
    assert sorted(df["cur"].tolist()) == ["EUR", "USD", "USD"]
