"""`apply_enrichment` must not lose column types (plan 085).

Types were inferred from the produced Python values, so an empty input, or an
upstream column that was NULL in every row, came back as int32. Chained
http_lookup steps then created timestamp/text destination columns as integer.
"""
import pyarrow as pa

from dte.engine.base import EnrichmentSpec
from dte.engine.duckdb_engine import DuckDBEngine


def _table(engine, rows):
    schema = pa.schema([("name", pa.string()), ("seen", pa.timestamp("us")), ("n", pa.int64())])
    return engine.con.create_table("src", pa.Table.from_pydict(rows, schema=schema))


def _spec(produce):
    return EnrichmentSpec(name="t", mapper=produce,
                          output_schema={"label": "VARCHAR", "score": "DOUBLE"})


def test_empty_input_keeps_upstream_and_declared_types():
    e = DuckDBEngine()
    out = e.apply_enrichment(_table(e, {"name": [], "seen": [], "n": []}), _spec(lambda r: [{}]))
    s = out.schema()
    assert s["name"].is_string() and s["seen"].is_timestamp() and s["n"].is_integer()
    assert s["label"].is_string() and s["score"].is_floating()


def test_all_null_columns_keep_their_types():
    e = DuckDBEngine()
    t = _table(e, {"name": [None, None], "seen": [None, None], "n": [1, 2]})
    out = e.apply_enrichment(t, _spec(lambda r: [{"label": None, "score": None}]))
    s = out.schema()
    assert s["name"].is_string() and s["seen"].is_timestamp()
    assert s["label"].is_string() and s["score"].is_floating()


def test_undeclared_mapper_columns_are_still_kept():
    e = DuckDBEngine()
    t = _table(e, {"name": ["a"], "seen": [None], "n": [1]})
    out = e.apply_enrichment(t, _spec(lambda r: [{"label": "x", "extra": 7}]))
    assert out.execute()["extra"].tolist() == [7]
