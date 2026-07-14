from __future__ import annotations
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field, model_validator


class Source(BaseModel):
    id: str
    source_type: str
    config: dict
    table: str


# Back-compat alias — deprecated. Delete after plan 015 lands end-to-end.
DltSource = Source


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


class SelectStep(BaseModel):
    op: Literal["select"]
    fields: list["OutputField"] = []
    drop: list[str] = []

    @model_validator(mode="after")
    def _check_exclusive(self):
        if self.fields and self.drop:
            raise ValueError("SelectStep: `fields` and `drop` are mutually exclusive")
        if not self.fields and not self.drop:
            raise ValueError("SelectStep: one of `fields` or `drop` is required")
        return self


class JoinStep(BaseModel):
    op: Literal["join"]
    left: str
    right: str
    on: str | list[str]
    how: Literal["inner", "left", "right", "outer"] = "inner"
    output_id: str


class PivotStep(BaseModel):
    op: Literal["pivot"]
    index: str | list[str]
    columns: str
    values: str
    agg: Literal["sum", "count", "avg", "min", "max"] = "sum"


class OutputField(BaseModel):
    field: str
    alias: str | None = None


class JsonFileTarget(BaseModel):
    type: Literal["json_file"]
    path: str
    fields: list[OutputField] = []


# Back-compat alias for callers still importing the old name.
JsonFileOutput = JsonFileTarget


class CsvFileTarget(BaseModel):
    type: Literal["csv_file"]
    path: str
    fields: list[OutputField] = []


class ParquetS3Target(BaseModel):
    type: Literal["parquet_s3"]
    bucket_url: str
    storage_options: dict = {}


class PostgresTarget(BaseModel):
    type: Literal["postgres"]
    credentials: str
    schema_: str = Field(alias="schema")
    table: str
    write_disposition: Literal["replace", "append", "merge"] = "replace"

    model_config = {"populate_by_name": True}


class SqlDatabaseTarget(BaseModel):
    type: Literal["sql_database"]
    dialect: Literal["mysql", "snowflake", "bigquery"]
    credentials: str
    schema_: str = Field(alias="schema")
    table: str
    write_disposition: Literal["replace", "append", "merge"] = "replace"

    model_config = {"populate_by_name": True}


OutputTarget = Annotated[
    Union[
        JsonFileTarget,
        CsvFileTarget,
        ParquetS3Target,
        PostgresTarget,
        SqlDatabaseTarget,
    ],
    Field(discriminator="type"),
]


class Destination(BaseModel):
    id: str
    config: OutputTarget


class Pipeline(BaseModel):
    id: str
    name: str
    sources: list[str]
    steps: list[dict]
    output_id: str
