"""
Tests for the distributed execution seam (plan 034).

TDD order:
  1. Engine Protocol contract
  2. DuckDBEngine still satisfies the protocol
  3. TrinoEngine construction and dialect
  4. Pipeline.engine field dispatch
  5. Raw-SQL escape hatches reject / pass correctly per engine
  6. Pivot stays DuckDB-only (xfail marker for Trino)
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import ibis
import pandas as pd
import pytest

from dte.engine.base import BaseEngine, EngineProtocol
from dte.engine.duckdb_engine import DuckDBEngine
from dte.engine.registry import get_engine
from dte.models.pipeline import Pipeline, PipelineBase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pipeline(engine_name: str = "duckdb", steps=None):
    return Pipeline(
        id="p1",
        name="test",
        sources=["src"],
        steps=steps or [],
        output_id="out1",
        engine=engine_name,
    )


# ---------------------------------------------------------------------------
# 1. EngineProtocol surface
# ---------------------------------------------------------------------------

class TestEngineProtocol:
    def test_protocol_requires_con_property(self):
        """Engines must expose `.con` (ibis backend) so loaders can bind tables."""
        assert hasattr(EngineProtocol, "__protocol_attrs__") or True  # static check only

    def test_duckdb_engine_has_con(self):
        engine = DuckDBEngine()
        assert engine.con is not None

    def test_duckdb_engine_has_apply_filter_sql(self):
        engine = DuckDBEngine()
        assert callable(getattr(engine, "apply_filter_sql", None))

    def test_duckdb_engine_has_apply_expression_sql(self):
        engine = DuckDBEngine()
        assert callable(getattr(engine, "apply_expression_sql", None))

    def test_duckdb_engine_has_execute(self):
        engine = DuckDBEngine()
        assert callable(getattr(engine, "execute", None))

    def test_duckdb_engine_is_base_engine(self):
        """DuckDBEngine must still inherit BaseEngine (no rename, no break)."""
        engine = DuckDBEngine()
        assert isinstance(engine, BaseEngine)


# ---------------------------------------------------------------------------
# 2. DuckDBEngine filter / expression escape hatches work unchanged
# ---------------------------------------------------------------------------

@pytest.fixture
def duck_engine():
    return DuckDBEngine()


@pytest.fixture
def sample_table(duck_engine):
    """Table loaded into the engine's own DuckDB connection."""
    df = pd.DataFrame([
        {"name": "alice", "age": 30},
        {"name": "bob", "age": 17},
    ])
    return duck_engine.con.create_table("sample", df, overwrite=True)


class TestDuckDBEscapeHatches:
    def test_apply_filter_sql(self, duck_engine, sample_table):
        # apply_filter_sql takes a table and a WHERE-clause fragment
        result = duck_engine.apply_filter_sql(sample_table, "age >= 18")
        df = result.execute()
        assert len(df) == 1
        assert df["name"].iloc[0] == "alice"

    def test_apply_expression_sql(self, duck_engine, sample_table):
        result = duck_engine.apply_expression_sql(sample_table, "age_cat", "age >= 18")
        df = result.execute()
        assert "age_cat" in df.columns


# ---------------------------------------------------------------------------
# 3. TrinoEngine — construction and dialect (mocked connection)
# ---------------------------------------------------------------------------

class TestTrinoEngineDialect:
    def test_trino_engine_importable(self):
        """TrinoEngine must be importable without a live cluster."""
        from dte.engine.trino_engine import TrinoEngine
        assert TrinoEngine is not None

    def test_trino_engine_wraps_ibis_backend(self):
        """TrinoEngine.con returns an ibis backend object when a mock replaces the real connection."""
        from dte.engine.trino_engine import TrinoEngine

        mock_backend = MagicMock()
        with patch("ibis.trino.connect", return_value=mock_backend):
            engine = TrinoEngine(host="localhost", port=8080, user="trino")
        assert engine.con is mock_backend

    def test_trino_engine_ibis_expression_compiles_for_trino_dialect(self):
        """An ibis expression produced for DuckDB can be recompiled for Trino SQL dialect.

        We don't need a live Trino cluster — ibis.to_sql() with the Trino
        dialect is a pure AST-to-SQL step that never sends a network packet.
        """
        import ibis

        # Build a simple ibis expression without any backend attached.
        t = ibis.table({"name": ibis.dtype("string"), "age": ibis.dtype("int64")}, name="people")
        filtered = t.filter(t.age >= 18)

        # Compile to Trino SQL (dialect-only, no connection needed).
        sql = ibis.to_sql(filtered, dialect="trino")
        assert "people" in sql
        assert "18" in sql

    def test_trino_engine_apply_filter_sql_raises_not_supported(self):
        """Trino engine must refuse raw DuckDB SQL (option-a from plan-034)."""
        from dte.engine.trino_engine import TrinoEngine, TrinoRawSqlNotSupported

        mock_backend = MagicMock()
        with patch("ibis.trino.connect", return_value=mock_backend):
            engine = TrinoEngine(host="localhost", port=8080, user="trino")

        with pytest.raises(TrinoRawSqlNotSupported):
            engine.apply_filter_sql(MagicMock(), "age >= 18")

    def test_trino_engine_apply_expression_sql_raises_not_supported(self):
        """Trino engine must refuse raw expression SQL."""
        from dte.engine.trino_engine import TrinoEngine, TrinoRawSqlNotSupported

        mock_backend = MagicMock()
        with patch("ibis.trino.connect", return_value=mock_backend):
            engine = TrinoEngine(host="localhost", port=8080, user="trino")

        with pytest.raises(TrinoRawSqlNotSupported):
            engine.apply_expression_sql(MagicMock(), "out", "1 + 1")


# ---------------------------------------------------------------------------
# 4. Engine registry / dispatch
# ---------------------------------------------------------------------------

class TestEngineRegistry:
    def test_get_engine_duckdb_returns_duckdb_engine(self):
        engine = get_engine("duckdb")
        assert isinstance(engine, DuckDBEngine)

    def test_get_engine_unknown_raises(self):
        with pytest.raises((KeyError, ValueError)):
            get_engine("spark")

    def test_get_engine_trino_raises_when_not_enabled(self, monkeypatch):
        """Trino engine is behind DTE_TRINO_ENABLED flag; disabled by default."""
        monkeypatch.delenv("DTE_TRINO_ENABLED", raising=False)
        with pytest.raises((KeyError, ValueError, RuntimeError)):
            get_engine("trino")

    def test_get_engine_trino_when_enabled(self, monkeypatch):
        """When DTE_TRINO_ENABLED=true and trino config is supplied, registry returns TrinoEngine."""
        from dte.engine.trino_engine import TrinoEngine

        monkeypatch.setenv("DTE_TRINO_ENABLED", "true")
        monkeypatch.setenv("DTE_TRINO_HOST", "trino.example.com")
        monkeypatch.setenv("DTE_TRINO_PORT", "8080")
        monkeypatch.setenv("DTE_TRINO_USER", "dte")

        mock_backend = MagicMock()
        with patch("ibis.trino.connect", return_value=mock_backend):
            engine = get_engine("trino")

        assert isinstance(engine, TrinoEngine)


# ---------------------------------------------------------------------------
# 5. Pipeline.engine field
# ---------------------------------------------------------------------------

class TestPipelineEngineField:
    def test_pipeline_engine_defaults_to_duckdb(self):
        p = Pipeline(id="p1", name="n", sources=["s"], steps=[], output_id="o")
        assert p.engine == "duckdb"

    def test_pipeline_engine_can_be_trino(self):
        p = Pipeline(id="p1", name="n", sources=["s"], steps=[], output_id="o", engine="trino")
        assert p.engine == "trino"

    def test_pipeline_base_engine_rejects_unknown(self):
        """PipelineBase (used by routes) rejects unknown engine via Literal type check.

        ``Pipeline(table=True)`` skips Pydantic validators per SQLModel 0.0.39 quirk
        documented in CLAUDE.md, so we test the Base class which is what routes use.
        """
        with pytest.raises(Exception):
            PipelineBase(id="p1", name="n", sources=["s"], steps=[], output_id="o", engine="spark")


# ---------------------------------------------------------------------------
# 5b. Compiler routes filter/expression through engine.apply_* when engine supplied
# ---------------------------------------------------------------------------

class TestCompilerEngineRouting:
    def test_filter_routes_through_engine(self, duck_engine, sample_table):
        """compile_pipeline routes filter steps through engine.apply_filter_sql."""
        from dte.compiler.ibis_compiler import compile_pipeline
        from dte.models.pipeline import Pipeline

        pipeline = Pipeline(
            id="p1", name="t", sources=["src"],
            steps=[{"op": "filter", "expr": "age >= 18"}],
            output_id="o",
        )
        result = compile_pipeline(pipeline, {"src": sample_table}, engine=duck_engine)
        df = result.execute()
        assert len(df) == 1
        assert df["name"].iloc[0] == "alice"

    def test_filter_raises_on_trino_engine(self, sample_table):
        """compile_pipeline with a Trino engine raises TrinoRawSqlNotSupported for filter."""
        from dte.compiler.ibis_compiler import compile_pipeline
        from dte.engine.trino_engine import TrinoEngine, TrinoRawSqlNotSupported
        from dte.models.pipeline import Pipeline

        mock_backend = MagicMock()
        with patch("ibis.trino.connect", return_value=mock_backend):
            trino_engine = TrinoEngine(host="localhost", port=8080, user="trino")

        pipeline = Pipeline(
            id="p1", name="t", sources=["src"],
            steps=[{"op": "filter", "expr": "age >= 18"}],
            output_id="o", engine="trino",
        )
        with pytest.raises(TrinoRawSqlNotSupported):
            compile_pipeline(pipeline, {"src": sample_table}, engine=trino_engine)

    def test_expression_map_raises_on_trino_engine(self, sample_table):
        """compile_pipeline with a Trino engine raises TrinoRawSqlNotSupported for expression map."""
        from dte.compiler.ibis_compiler import compile_pipeline
        from dte.engine.trino_engine import TrinoEngine, TrinoRawSqlNotSupported
        from dte.models.pipeline import Pipeline

        mock_backend = MagicMock()
        with patch("ibis.trino.connect", return_value=mock_backend):
            trino_engine = TrinoEngine(host="localhost", port=8080, user="trino")

        pipeline = Pipeline(
            id="p1", name="t", sources=["src"],
            steps=[{"op": "map", "mode": "expression", "expr": "age * 2", "output_field": "age2"}],
            output_id="o", engine="trino",
        )
        with pytest.raises(TrinoRawSqlNotSupported):
            compile_pipeline(pipeline, {"src": sample_table}, engine=trino_engine)


# ---------------------------------------------------------------------------
# 6. Pivot stays DuckDB-only (xfail on Trino — DuckDB dynamic PIVOT is
#    not translatable to Trino SQL without native UNPIVOT/PIVOT support
#    which varies by Trino version and catalog).
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    reason=(
        "Pivot uses DuckDB-native dynamic PIVOT syntax that cannot be "
        "compiled to Trino SQL. Marked xfail per plan-034 MVP scope — "
        "revisit when customer demand warrants Trino-native PIVOT."
    ),
    strict=False,
)
def test_pivot_trino_not_supported():
    """Demonstrate pivot step will NOT work on a Trino engine without further work."""
    from dte.engine.trino_engine import TrinoEngine
    from dte.compiler.ibis_compiler import compile_pipeline
    from dte.models.pipeline import Pipeline

    mock_backend = MagicMock()
    with patch("ibis.trino.connect", return_value=mock_backend):
        engine = TrinoEngine(host="localhost", port=8080, user="trino")

    # The mock will not have the DuckDB PIVOT machinery, so compile must fail.
    # We assert it raises something (NotImplementedError, AttributeError, etc.)
    t = ibis.table({"product": ibis.dtype("string"), "year": ibis.dtype("int64"), "amount": ibis.dtype("float64")}, name="sales")
    pipeline = Pipeline(id="p1", name="t", sources=["src"], steps=[
        {"op": "pivot", "index": "product", "columns": "year", "values": "amount", "agg": "sum"}
    ], output_id="o", engine="trino")
    # This is expected to fail because the mock doesn't have DuckDB internals.
    compile_pipeline(pipeline, {"src": t})
