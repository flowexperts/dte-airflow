from __future__ import annotations
from typing import Literal
from pydantic import BaseModel


class DltSource(BaseModel):
    id: str
    source_type: str
    config: dict
    table: str


class FilterStep(BaseModel):
    op: Literal["filter"]
    expr: str


class RenameStep(BaseModel):
    op: Literal["rename"]
    mappings: dict[str, str]


class RetypeStep(BaseModel):
    op: Literal["retype"]
    field: str
    to_type: Literal["string", "int", "float", "boolean", "date", "timestamp"]


class LookupMapStep(BaseModel):
    op: Literal["map"]
    mode: Literal["lookup"]
    field: str
    table: dict[str, str]
    default: str | None = None


class ExpressionMapStep(BaseModel):
    op: Literal["map"]
    mode: Literal["expression", "calculation"]
    output_field: str
    expr: str


class SortStep(BaseModel):
    op: Literal["sort"]
    by: list[str]
    ascending: list[bool] | bool = True


class AggSpec(BaseModel):
    field: str
    func: Literal["sum", "count", "avg", "min", "max", "count_distinct"]
    alias: str


class AggregateStep(BaseModel):
    op: Literal["aggregate"]
    group_by: list[str]
    aggregations: list[AggSpec]


class OutputField(BaseModel):
    field: str
    alias: str | None = None


class JsonFileOutput(BaseModel):
    type: Literal["json_file"]
    path: str
    fields: list[OutputField] = []


class Pipeline(BaseModel):
    id: str
    name: str
    sources: list[DltSource]
    steps: list[dict]
    output: JsonFileOutput
