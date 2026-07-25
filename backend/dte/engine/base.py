from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

import ibis


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

    # ------------------------------------------------------------------
    # Legacy helper — kept for back-compat with call sites that only need
    # a JSON output path.
    # ------------------------------------------------------------------

    def execute_to_json(self, table: ibis.Table, output_path: str) -> int:
        from dte.models.pipeline import JsonFileTarget
        result = self.execute(table, JsonFileTarget(type="json_file", path=output_path))
        return result["rows_written"]
