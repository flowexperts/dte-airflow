from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import ibis


@dataclass(frozen=True)
class EnrichmentSpec:
    """A per-row Python map applied to a materialised table.

    Enrichment is the one thing in this engine that cannot be a lazy ibis
    expression. A model call is per-row, slow, rate-limited, retryable and
    billable; inside a DuckDB scan it would be re-evaluated on every
    downstream reference. So the seam materialises: SQL out, map in Python,
    register the result back.

    That is a deliberate laziness break — the same one `_apply_pivot` already
    makes — and it is what buys retries, per-row progress events, rate
    limiting and caching.

    `mapper` receives one input row as a dict and returns a list of *new*
    column dicts. Returning several fans the row out (one page per row);
    returning none drops it. The engine merges each result over the input row,
    so upstream columns survive without the mapper having to copy them.
    """

    name: str
    mapper: Callable[[dict[str, Any]], list[dict[str, Any]]]
    # Column name → SQL type, used to build a correctly-typed empty result
    # when every input row is dropped or the input was empty to begin with.
    output_schema: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class EngineProtocol(Protocol):
    """Minimum surface a compilation backend must expose.

    Defined as a Protocol so callers can type-check without inheriting.
    All concrete engines inherit ``BaseEngine`` which satisfies this protocol.

    Seam from plan-034: filter/expression-map escape hatches delegate to the
    engine so each backend can decide how to handle raw SQL.  DuckDB materialises
    a view; Trino raises ``TrinoRawSqlNotSupported`` (option-a from plan-034).
    """

    @property
    def con(self) -> ibis.BaseBackend:
        """The ibis backend — loaders bind source tables here."""
        ...

    def apply_filter_sql(self, table: ibis.Table, expr: str) -> ibis.Table:
        """Apply a raw SQL WHERE-clause fragment to *table*."""
        ...

    def apply_expression_sql(
        self, table: ibis.Table, output_field: str, expr: str
    ) -> ibis.Table:
        """Add a computed column *output_field* evaluated from *expr* (raw SQL)."""
        ...

    def execute(self, table: ibis.Table, target, credentials: dict | None = None) -> dict:
        """Execute *table* and write to *target*; return ``{rows_written, location}``."""
        ...


class BaseEngine(ABC):
    """Abstract base that all concrete engines inherit.

    Satisfies ``EngineProtocol`` structurally; subclasses only need to
    implement the abstract methods below.
    """

    # SQL dialect passed to ``ibis.to_sql`` when the compiler or preview
    # endpoints render per-step / final SQL (plan-039).  Concrete engines
    # override with their native dialect name.
    dialect: str = "duckdb"

    @property
    @abstractmethod
    def con(self) -> ibis.BaseBackend:
        ...

    @abstractmethod
    def apply_filter_sql(self, table: ibis.Table, expr: str) -> ibis.Table:
        ...

    @abstractmethod
    def apply_expression_sql(
        self, table: ibis.Table, output_field: str, expr: str
    ) -> ibis.Table:
        ...

    @abstractmethod
    def execute(self, table: ibis.Table, target, credentials: dict | None = None) -> dict:
        ...

    def apply_enrichment(
        self, table: ibis.Table, spec: EnrichmentSpec
    ) -> ibis.Table:
        """Materialise *table*, map every row through `spec`, register the result.

        Default implementation refuses: a backend that can't run a Python
        mapper over its rows must say so rather than silently doing something
        else. `DuckDBEngine` overrides it.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support enrichment steps"
        )

    # ------------------------------------------------------------------
    # Legacy helper — kept for back-compat with call sites that only need
    # a JSON output path.
    # ------------------------------------------------------------------

    def execute_to_json(self, table: ibis.Table, output_path: str) -> int:
        from dte.models.pipeline import JsonFileTarget
        result = self.execute(table, JsonFileTarget(type="json_file", path=output_path))
        return result["rows_written"]
