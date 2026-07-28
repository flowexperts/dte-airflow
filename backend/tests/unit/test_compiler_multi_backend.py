"""Unit tests for the compiler's multi-backend detection.

Pipelines whose source tables span more than one ibis backend (e.g.
postgres + duckdb) are rejected at compile time with a MixedBackendError,
since ibis can't cross-execute joins without a federator.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import ibis
import pytest

from dte.compiler.ibis_compiler import (
    MixedBackendError,
    _check_single_backend,
    compile_pipeline,
)
from dte.models.pipeline import Pipeline


def test_single_duckdb_backend_passes():
    con = ibis.duckdb.connect()
    con.raw_sql("CREATE TABLE t AS SELECT 1 AS x")
    _check_single_backend({"a": con.table("t")})  # no exception


def test_two_tables_same_duckdb_pass():
    con = ibis.duckdb.connect()
    con.raw_sql("CREATE TABLE a AS SELECT 1 AS x")
    con.raw_sql("CREATE TABLE b AS SELECT 1 AS y")
    _check_single_backend({"a": con.table("a"), "b": con.table("b")})


def test_two_distinct_duckdb_backends_raises_mixed_backend():
    con_a = ibis.duckdb.connect()
    con_b = ibis.duckdb.connect()
    con_a.raw_sql("CREATE TABLE t AS SELECT 1 AS x")
    con_b.raw_sql("CREATE TABLE t AS SELECT 1 AS x")
    with pytest.raises(MixedBackendError) as ei:
        _check_single_backend({"a": con_a.table("t"), "b": con_b.table("t")})
    # Payload includes per-source backend map.
    assert set(ei.value.source_backends.keys()) == {"a", "b"}


def test_empty_tables_no_error():
    _check_single_backend({})


def test_compile_pipeline_raises_mixed_backend_error():
    con_a = ibis.duckdb.connect()
    con_b = ibis.duckdb.connect()
    con_a.raw_sql("CREATE TABLE orders (id INT)")
    con_b.raw_sql("CREATE TABLE customers (id INT)")
    pipeline = Pipeline(
        id="mixed",
        name="mixed",
        sources=["orders", "customers"],
        output_id="out",
        steps=[],
    )
    tables = {
        "orders": con_a.table("orders"),
        "customers": con_b.table("customers"),
    }
    with pytest.raises(MixedBackendError):
        compile_pipeline(pipeline, tables)
