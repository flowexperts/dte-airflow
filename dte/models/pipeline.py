from __future__ import annotations
from enum import Enum
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field


class SourceType(str, Enum):
    JSON_FILE = "json_file"
    CSV_FILE = "csv_file"
    POSTGRES = "postgres"


class JsonFileSource(BaseModel):
    id: str
    type: Literal["json_file"]
    path: str


class CsvFileSource(BaseModel):
    id: str
    type: Literal["csv_file"]
    path: str


class PostgresSource(BaseModel):
    id: str
    type: Literal["postgres"]
    connection_string: str
    table: str


Source = Annotated[
    Union[JsonFileSource, CsvFileSource, PostgresSource],
    Field(discriminator="type")
]


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
    sources: list[Source]
    steps: list[dict]
    output: JsonFileOutput
