"""Airflow 3.3 pins sqlglot 30, which moved Drop's target from `this` to
`tables`; ibis 12 still passes `this`, so every DROP lost its name (plan 073)."""
import sqlglot as sg
import sqlglot.expressions as sge

import dte  # noqa: F401  (applies the shim)


def test_ibis_style_drop_keeps_its_name():
    drop = sge.Drop(kind="VIEW", this=sg.table("ibis_meta"), exists=True)
    assert drop.sql("postgres") == "DROP VIEW IF EXISTS ibis_meta"


def test_parsed_drop_unchanged():
    assert sg.parse_one("DROP TABLE t", read="duckdb").sql("duckdb") == "DROP TABLE t"
