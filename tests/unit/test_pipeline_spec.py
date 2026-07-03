import pytest
from pydantic import ValidationError
from dte.models.pipeline import (
    JsonFileSource, CsvFileSource, PostgresSource,
    FilterStep, RenameStep, RetypeStep,
    LookupMapStep, ExpressionMapStep,
    SortStep, AggSpec, AggregateStep,
    OutputField, JsonFileOutput, Pipeline,
)


def test_json_source_parses():
    s = JsonFileSource(id="s1", type="json_file", path="/data/foo.json")
    assert s.id == "s1"
    assert s.type == "json_file"
    assert s.path == "/data/foo.json"


def test_postgres_source_parses():
    s = PostgresSource(
        id="s2", type="postgres",
        connection_string="postgresql://localhost/db",
        table="orders"
    )
    assert s.table == "orders"


def test_invalid_source_type_raises():
    with pytest.raises(ValidationError):
        JsonFileSource(id="s1", type="invalid", path="/foo")


def test_filter_step_in_pipeline():
    p = Pipeline(
        id="p1", name="test",
        sources=[{"id": "s1", "type": "json_file", "path": "/foo.json"}],
        steps=[{"op": "filter", "expr": "age > 18"}],
        output={"type": "json_file", "path": "/out.json"},
    )
    assert p.steps[0]["op"] == "filter"
    step = FilterStep(**p.steps[0])
    assert step.expr == "age > 18"


def test_rename_step_in_pipeline():
    p = Pipeline(
        id="p1", name="test",
        sources=[{"id": "s1", "type": "json_file", "path": "/foo.json"}],
        steps=[{"op": "rename", "mappings": {"old_name": "new_name"}}],
        output={"type": "json_file", "path": "/out.json"},
    )
    step = RenameStep(**p.steps[0])
    assert step.mappings == {"old_name": "new_name"}


def test_retype_step_in_pipeline():
    p = Pipeline(
        id="p1", name="test",
        sources=[{"id": "s1", "type": "json_file", "path": "/foo.json"}],
        steps=[{"op": "retype", "field": "age", "to_type": "string"}],
        output={"type": "json_file", "path": "/out.json"},
    )
    step = RetypeStep(**p.steps[0])
    assert step.field == "age"
    assert step.to_type == "string"


def test_lookup_map_step_in_pipeline():
    p = Pipeline(
        id="p1", name="test",
        sources=[{"id": "s1", "type": "json_file", "path": "/foo.json"}],
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
        sources=[{"id": "s1", "type": "json_file", "path": "/foo.json"}],
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
        sources=[{"id": "s1", "type": "json_file", "path": "/foo.json"}],
        steps=[{"op": "sort", "by": ["age", "name"], "ascending": [True, False]}],
        output={"type": "json_file", "path": "/out.json"},
    )
    step = SortStep(**p.steps[0])
    assert step.by == ["age", "name"]
    assert step.ascending == [True, False]


def test_aggregate_step_in_pipeline():
    p = Pipeline(
        id="p1", name="test",
        sources=[{"id": "s1", "type": "json_file", "path": "/foo.json"}],
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
        sources=[{"id": "s1", "type": "json_file", "path": "/foo.json"}],
        steps=[],
        output={
            "type": "json_file", "path": "/out.json",
            "fields": [{"field": "name", "alias": "full_name"}, {"field": "age"}]
        },
    )
    assert p.output.fields[0].alias == "full_name"
    assert p.output.fields[1].alias is None
