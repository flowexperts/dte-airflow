"""Unit tests for the DuckDB engine singleton pool (dte/sources/pools/engine.py).

Tests cover:
- get_engine returns the same DuckDBEngine instance on repeated calls
- reset_engine clears the singleton (test utility)
- pool disabled: each call returns a fresh engine
- pool enabled: second call is a cache hit
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dte.sources.pools.engine import get_engine, reset_engine


@pytest.fixture(autouse=True)
def _clean_engine():
    reset_engine()
    yield
    reset_engine()


# ---------------------------------------------------------------------------
# Cache hit / miss
# ---------------------------------------------------------------------------


def test_get_engine_returns_same_instance():
    """Two calls with default flag state return the same DuckDBEngine."""
    with patch("dte.sources.pools.engine._pool_enabled", True):
        engine_a = get_engine()
        engine_b = get_engine()
    assert engine_a is engine_b


def test_get_engine_disabled_returns_fresh_each_time():
    """When pool is disabled, each call produces a new DuckDBEngine."""
    with patch("dte.sources.pools.engine._pool_enabled", False):
        engine_a = get_engine()
        engine_b = get_engine()
    assert engine_a is not engine_b


def test_reset_engine_clears_singleton():
    with patch("dte.sources.pools.engine._pool_enabled", True):
        engine_a = get_engine()
        reset_engine()
        engine_b = get_engine()
    assert engine_a is not engine_b


def test_get_engine_returns_duckdb_engine():
    """get_engine must return a DuckDBEngine, not a bare ibis backend."""
    from dte.engine.duckdb_engine import DuckDBEngine

    engine = get_engine()
    assert isinstance(engine, DuckDBEngine)
    # Cleanup
    engine.con.disconnect()
