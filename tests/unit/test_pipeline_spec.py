import pytest
from pydantic import ValidationError
from dte.models.pipeline import (
    DltSource,
    FilterStep, RenameStep, RetypeStep,
    LookupMapStep, ExpressionMapStep,
    SortStep, AggSpec, AggregateStep,
    OutputField, JsonFileOutput, Pipeline,
    JoinStep, PivotStep,
)


def test_dlt_source_parses():
    s = DltSource(
        id="s1",
        source_type="filesystem",
        config={"bucket_url": "/tmp/data", "file_glob": "*.json"},
        table="data",
    )
    assert s.id == "s1"
    assert s.source_type == "filesystem"
    assert s.config["bucket_url"] == "/tmp/data"
    assert s.table == "data"


def test_pipeline_with_dlt_source():
    p = Pipeline(
        id="p1", name="test",
        sources=[{
            "id": "s1",
            "source_type": "filesystem",
            "config": {"bucket_url": "s3://my-bucket/", "file_glob": "*.json"},
            "table": "records",
        }],
        steps=[{"op": "filter", "expr": "age > 18"}],
        output={"type": "json_file", "path": "/out.json"},
    )
    assert len(p.sources) == 1
    assert p.sources[0].id == "s1"
    assert p.sources[0].table == "records"


def test_invalid_source_missing_table_raises():
    with pytest.raises(ValidationError):
        DltSource(id="s1", source_type="filesystem", config={})


def test_filter_step_in_pipeline():
    p = Pipeline(
        id="p1", name="test",
        sources=[{
            "id": "s1", "source_type": "filesystem",
            "config": {"bucket_url": "/tmp"}, "table": "t",
        }],
        steps=[{"op": "filter", "expr": "age > 18"}],
        output={"type": "json_file", "path": "/out.json"},
    )
    assert p.steps[0]["op"] == "filter"
    step = FilterStep(**p.steps[0])
    assert step.expr == "age > 18"


def test_rename_step_in_pipeline():
    p = Pipeline(
        id="p1", name="test",
        sources=[{
            "id": "s1", "source_type": "filesystem",
            "config": {"bucket_url": "/tmp"}, "table": "t",
        }],
        steps=[{"op": "rename", "mappings": {"old_name": "new_name"}}],
        output={"type": "json_file", "path": "/out.json"},
    )
    step = RenameStep(**p.steps[0])
    assert step.mappings == {"old_name": "new_name"}


def test_retype_step_in_pipeline():
    p = Pipeline(
        id="p1", name="test",
        sources=[{
            "id": "s1", "source_type": "filesystem",
            "config": {"bucket_url": "/tmp"}, "table": "t",
        }],
        steps=[{"op": "retype", "field": "age", "to_type": "string"}],
        output={"type": "json_file", "path": "/out.json"},
    )
    step = RetypeStep(**p.steps[0])
    assert step.field == "age"
    assert step.to_type == "string"


def test_lookup_map_step_in_pipeline():
    p = Pipeline(
        id="p1", name="test",
        sources=[{
            "id": "s1", "source_type": "filesystem",
            "config": {"bucket_url": "/tmp"}, "table": "t",
        }],
        steps=[{
            "op": "map", "mode": "lookup", "field": "country_code",
            "table": {"US": "United States", "CA": "Canada"},
            "default": "Unknown"
        }],
        output={"type": "json_file", "path": "/out.json"},
    )
    step = LookupMapStep(**p.steps[0])
    assert step.table["US"] == "United States"
    assert step.default == "Unknown"


def test_expression_map_step_in_pipeline():
    p = Pipeline(
        id="p1", name="test",
        sources=[{
            "id": "s1", "source_type": "filesystem",
            "config": {"bucket_url": "/tmp"}, "table": "t",
        }],
        steps=[{
            "op": "map", "mode": "expression",
            "output_field": "total", "expr": "price * quantity"
        }],
        output={"type": "json_file", "path": "/out.json"},
    )
    step = ExpressionMapStep(**p.steps[0])
    assert step.output_field == "total"
    assert step.expr == "price * quantity"


def test_sort_step_in_pipeline():
    p = Pipeline(
        id="p1", name="test",
        sources=[{
            "id": "s1", "source_type": "filesystem",
            "config": {"bucket_url": "/tmp"}, "table": "t",
        }],
        steps=[{"op": "sort", "by": ["age", "name"], "ascending": [True, False]}],
        output={"type": "json_file", "path": "/out.json"},
    )
    step = SortStep(**p.steps[0])
    assert step.by == ["age", "name"]
    assert step.ascending == [True, False]


def test_aggregate_step_in_pipeline():
    p = Pipeline(
        id="p1", name="test",
        sources=[{
            "id": "s1", "source_type": "filesystem",
            "config": {"bucket_url": "/tmp"}, "table": "t",
        }],
        steps=[{
            "op": "aggregate",
            "group_by": ["category"],
            "aggregations": [{"field": "amount", "func": "sum", "alias": "total"}]
        }],
        output={"type": "json_file", "path": "/out.json"},
    )
    step = AggregateStep(**p.steps[0])
    assert step.group_by == ["category"]
    assert step.aggregations[0].func == "sum"


def test_pipeline_output_fields():
    p = Pipeline(
        id="p1", name="test",
        sources=[{
            "id": "s1", "source_type": "filesystem",
            "config": {"bucket_url": "/tmp"}, "table": "t",
        }],
        steps=[],
        output={
            "type": "json_file", "path": "/out.json",
            "fields": [{"field": "name", "alias": "full_name"}, {"field": "age"}]
        },
    )
    assert p.output.fields[0].alias == "full_name"
    assert p.output.fields[1].alias is None


def test_join_step_parses():
    step = JoinStep(
        op="join",
        left="users",
        right="orders",
        on="id",
        how="inner",
        output_id="joined",
    )
    assert step.left == "users"
    assert step.right == "orders"
    assert step.on == "id"
    assert step.how == "inner"
    assert step.output_id == "joined"


def test_join_step_defaults_inner():
    step = JoinStep(op="join", left="a", right="b", on="id", output_id="ab")
    assert step.how == "inner"


def test_pivot_step_parses():
    step = PivotStep(
        op="pivot",
        index="region",
        columns="product",
        values="sales",
        agg="sum",
    )
    assert step.index == "region"
    assert step.columns == "product"
    assert step.values == "sales"
    assert step.agg == "sum"


def test_pivot_step_default_agg_is_sum():
    step = PivotStep(op="pivot", index="region", columns="product", values="sales")
    assert step.agg == "sum"
