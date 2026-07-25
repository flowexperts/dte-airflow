"""DTE engine package — plan-034 distributed execution seam.

Public surface:
  ``get_engine(name)`` — obtain a concrete engine by name ("duckdb" | "trino").
  ``BaseEngine``       — ABC for implementing new engines.
  ``EngineProtocol``   — structural Protocol for type-checking.
"""
from dte.engine.base import BaseEngine, EngineProtocol
from dte.engine.duckdb_engine import DuckDBEngine
from dte.engine.registry import get_engine

__all__ = ["BaseEngine", "DuckDBEngine", "EngineProtocol", "get_engine"]
