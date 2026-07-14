import pytest
from pydantic import ValidationError
from dte.models.pipeline import (
    Source, Destination,
    FilterStep, RenameStep, RetypeStep,
    LookupMapStep, ExpressionMapStep,
    SortStep, AggSpec, AggregateStep,
    OutputField, JsonFileOutput, Pipeline,
    JoinStep, PivotStep, SelectStep,
)


def _pipeline(**overrides):
    base = dict(
        id="p1", name="test",
        sources=["s1"],
        steps=[],
        output_id="out1",
    )
    base.update(overrides)
    return Pipeline(**base)


def test_source_parses():
    s = Source(
        id="s1",
        source_type="filesystem",
        config={"bucket_url": "/tmp/data", "file_glob": "*.json"},
        table="data",
    )
    assert s.id == "s1"
    assert s.source_type == "filesystem"
    assert s.config["bucket_url"] == "/tmp/data"
    assert s.table == "data"


def test_destination_parses():
    d = Destination(id="out1", config={"type": "json_file", "path": "/out.json"})
    assert d.id == "out1"
    assert d.config.type == "json_file"
    assert d.config.path == "/out.json"


def test_pipeline_holds_source_ids_and_output_id():
    p = _pipeline(sources=["s1", "s2"], output_id="dest_x")
    assert p.sources == ["s1", "s2"]
    assert p.output_id == "dest_x"


def test_invalid_source_missing_table_raises():
    with pytest.raises(ValidationError):
        Source(id="s1", source_type="filesystem", config={})


def test_filter_step_in_pipeline():
    p = _pipeline(steps=[{"op": "filter", "expr": "age > 18"}])
    step = FilterStep(**p.steps[0])
    assert step.expr == "age > 18"


def test_rename_step_in_pipeline():
    p = _pipeline(steps=[{"op": "rename", "mappings": {"old_name": "new_name"}}])
    step = RenameStep(**p.steps[0])
    assert step.mappings == {"old_name": "new_name"}


def test_retype_step_in_pipeline():
    p = _pipeline(steps=[{"op": "retype", "field": "age", "to_type": "string"}])
    step = RetypeStep(**p.steps[0])
    assert step.field == "age"
    assert step.to_type == "string"


def test_lookup_map_step_in_pipeline():
    p = _pipeline(steps=[{
        "op": "map", "mode": "lookup", "field": "country_code",
        "table": {"US": "United States", "CA": "Canada"},
        "default": "Unknown"
    }])
    step = LookupMapStep(**p.steps[0])
    assert step.table["US"] == "United States"
    assert step.default == "Unknown"


def test_expression_map_step_in_pipeline():
    p = _pipeline(steps=[{
        "op": "map", "mode": "expression",
        "output_field": "total", "expr": "price * quantity"
    }])
    step = ExpressionMapStep(**p.steps[0])
    assert step.output_field == "total"
    assert step.expr == "price * quantity"


def test_sort_step_in_pipeline():
    p = _pipeline(steps=[{"op": "sort", "by": ["age", "name"], "ascending": [True, False]}])
    step = SortStep(**p.steps[0])
    assert step.by == ["age", "name"]
    assert step.ascending == [True, False]


def test_aggregate_step_in_pipeline():
    p = _pipeline(steps=[{
        "op": "aggregate",
        "group_by": ["category"],
        "aggregations": [{"field": "amount", "func": "sum", "alias": "total"}]
    }])
    step = AggregateStep(**p.steps[0])
    assert step.group_by == ["category"]
    assert step.aggregations[0].func == "sum"


def test_destination_output_fields():
    d = Destination(
        id="out1",
        config={
            "type": "json_file", "path": "/out.json",
            "fields": [{"field": "name", "alias": "full_name"}, {"field": "age"}]
        },
    )
    assert d.config.fields[0].alias == "full_name"
    assert d.config.fields[1].alias is None


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


def test_select_step_with_fields():
    step = SelectStep(op="select", fields=[{"field": "name"}, {"field": "age", "alias": "years"}])
    assert step.fields[1].alias == "years"
    assert step.drop == []


def test_select_step_with_drop():
    step = SelectStep(op="select", drop=["ssn", "internal_id"])
    assert step.drop == ["ssn", "internal_id"]
    assert step.fields == []


def test_select_step_fields_and_drop_mutually_exclusive():
    with pytest.raises(ValidationError):
        SelectStep(op="select", fields=[{"field": "name"}], drop=["ssn"])


def test_select_step_requires_one_of_fields_or_drop():
    with pytest.raises(ValidationError):
        SelectStep(op="select")
