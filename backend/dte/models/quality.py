"""Data-quality contract models.

Plan 029: declarative expectations on pipeline output, evaluated at the end of
each successful run and surfaced on the run detail page.

Contract types (discriminated union on `type`):
  - row_count_between   — row count in [min, max]
  - column_not_null     — zero NULLs in column
  - column_unique       — all values distinct
  - column_in_range     — all values in [min, max] (either bound optional)
  - column_matches      — all values match a regex

Each contract has a `severity`: "fail" downgrades the run to `failed_quality`;
"warn" produces `completed_with_warnings`.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class RowCountBetween(BaseModel):
    type: Literal["row_count_between"] = "row_count_between"
    id: str
    min: int
    max: int
    severity: Literal["warn", "fail"] = "fail"


class ColumnNotNull(BaseModel):
    type: Literal["column_not_null"] = "column_not_null"
    id: str
    column: str
    severity: Literal["warn", "fail"] = "fail"


class ColumnUnique(BaseModel):
    type: Literal["column_unique"] = "column_unique"
    id: str
    column: str
    severity: Literal["warn", "fail"] = "fail"


class ColumnInRange(BaseModel):
    type: Literal["column_in_range"] = "column_in_range"
    id: str
    column: str
    min: float | None = None
    max: float | None = None
    severity: Literal["warn", "fail"] = "fail"


class ColumnMatches(BaseModel):
    type: Literal["column_matches"] = "column_matches"
    id: str
    column: str
    regex: str
    severity: Literal["warn", "fail"] = "fail"


Contract = Annotated[
    RowCountBetween | ColumnNotNull | ColumnUnique | ColumnInRange | ColumnMatches,
    Field(discriminator="type"),
]


class QualityResult(BaseModel):
    """The outcome of evaluating one Contract against actual output data."""
    contract_id: str
    contract_type: str
    label: str | None = None  # human-readable name for the check (step label or contract column)
    passed: bool
    severity: str  # "warn" | "fail" — copied from the contract at eval time
    detail: str | None = None  # human-readable explanation, e.g. "5 nulls in 1000 rows"
