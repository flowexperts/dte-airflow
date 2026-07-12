import pytest
import json
from dte.schema.inferrer import infer_from_json


def test_flat_json_infers_string(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps([{"name": "alice"}, {"name": "bob"}]))
    result = infer_from_json(str(p))
    assert result["name"] == "string"


def test_flat_json_infers_int(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps([{"age": 30}, {"age": 25}]))
    result = infer_from_json(str(p))
    assert result["age"] == "int"


def test_flat_json_infers_float(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps([{"score": 9.5}, {"score": 8.0}]))
    result = infer_from_json(str(p))
    assert result["score"] == "float"


def test_flat_json_infers_boolean(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps([{"active": True}, {"active": False}]))
    result = infer_from_json(str(p))
    assert result["active"] == "boolean"


def test_nested_json_dot_notation(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps([{"user": {"city": "NYC", "zip": "10001"}}]))
    result = infer_from_json(str(p))
    assert result["user.city"] == "string"
    assert result["user.zip"] == "string"


def test_mixed_types_coerce_to_string(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps([{"val": 42}, {"val": "hello"}]))
    result = infer_from_json(str(p))
    assert result["val"] == "string"


def test_int_and_float_coerce_to_float(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps([{"val": 1}, {"val": 2.5}]))
    result = infer_from_json(str(p))
    assert result["val"] == "float"


def test_missing_field_in_some_rows(tmp_path):
    p = tmp_path / "data.json"
    p.write_text(json.dumps([{"a": 1, "b": "x"}, {"a": 2}]))
    result = infer_from_json(str(p))
    assert result["a"] == "int"
    assert result["b"] == "string"


def test_sample_size_respected(tmp_path):
    p = tmp_path / "data.json"
    rows = [{"val": i} for i in range(200)]
    p.write_text(json.dumps(rows))
    result = infer_from_json(str(p), sample_size=50)
    assert result["val"] == "int"
