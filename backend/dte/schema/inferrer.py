from __future__ import annotations

import json
from datetime import datetime


def infer_from_json(path: str, sample_size: int = 1000) -> dict[str, str]:
    with open(path) as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = [data]

    rows = data[:sample_size]
    field_types: dict[str, str] = {}

    for row in rows:
        flat = _flatten(row)
        for key, value in flat.items():
            vtype = _infer_value_type(value)
            if key in field_types:
                field_types[key] = _merge_types(field_types[key], vtype)
            else:
                field_types[key] = vtype

    return field_types


def _flatten(obj: dict, prefix: str = "") -> dict[str, object]:
    result = {}
    for k, v in obj.items():
        full_key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            result.update(_flatten(v, full_key))
        elif isinstance(v, list):
            if v and isinstance(v[0], dict):
                result.update(_flatten(v[0], full_key))
            else:
                elem_type = _infer_value_type(v[0]) if v else "null"
                result[full_key] = f"{elem_type}_list"
        else:
            result[full_key] = v
    return result


def _infer_value_type(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return "date"
        except ValueError:
            pass
        return "string"
    return "string"


def _merge_types(t1: str, t2: str) -> str:
    if t1 == t2:
        return t1
    if t1 == "null":
        return t2
    if t2 == "null":
        return t1
    if set([t1, t2]) == {"int", "float"}:
        return "float"
    return "string"
