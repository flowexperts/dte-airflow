"""Metered sources (plan 093): warehouse tables are previewed from a cached
sample, priced before a run, and capped on the connection. Nothing here
talks to a real warehouse."""
from __future__ import annotations

import logging
import sys
from types import ModuleType
from types import SimpleNamespace as NS

import ibis
import pyarrow as pa
import pytest

from dte.engine.backend_registry import BackendRegistry
from dte.models.pipeline import Connection, Source
from dte.sources import metered
from dte.sources import sample as sample_mod

BQ = Connection(id="bq", connection_type="bigquery", credentials={"url": "bigquery://prj"})


def _bq_source(schema="bigquery-public-data.samples") -> Source:
    return Source(id="bq_samples", connection_id="bq", source_type="sql_database",
                  table="bq_samples", config={"schema": schema})


class _FakeClient:
    def __init__(self, rows=3, time_field="timestamp", range_field=None):
        self.calls: list = []
        self.rows, self.time_field, self.range_field = rows, time_field, range_field

    def list_rows(self, table_id, max_results):
        self.calls.append(("list_rows", table_id, max_results))
        return NS(to_arrow=lambda: pa.table({"word": ["a"] * self.rows, "n": list(range(self.rows))}))

    def get_table(self, table_id):
        self.calls.append(("get_table", table_id))
        tp = None if self.time_field is False else NS(field=self.time_field)
        rp = NS(field=self.range_field) if self.range_field else None
        return NS(time_partitioning=tp, range_partitioning=rp)

    def query(self, sql, job_config=None):
        self.calls.append(("query", sql, job_config.kw))
        return NS(total_bytes_processed=3_127_887_272_858)


@pytest.fixture
def fake_bq(monkeypatch):
    mod = ModuleType("google.cloud.bigquery")

    class QueryJobConfig:
        def __init__(self, **kw):
            self.kw = kw

    mod.QueryJobConfig = QueryJobConfig
    for m in ("google", "google.cloud"):
        monkeypatch.setitem(sys.modules, m, sys.modules.get(m) or ModuleType(m))
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", mod)
    monkeypatch.setattr(sys.modules["google.cloud"], "bigquery", mod, raising=False)
    return NS(name="bigquery", client=_FakeClient())


def test_only_warehouse_sql_sources_are_metered():
    assert metered.is_metered(_bq_source(), BQ)
    pg = Connection(id="pg", connection_type="postgres", credentials={})
    assert not metered.is_metered(_bq_source(), pg)
    rest = Source(id="r", connection_id="bq", source_type="rest_api", table="r", config={})
    assert not metered.is_metered(rest, BQ)


def test_bigquery_sample_uses_tabledata_list_never_a_query(fake_bq):
    t = metered.fetch_sample(fake_bq, "bigquery", "bigquery-public-data.samples", "shakespeare", 1000)
    assert t.num_rows == 3
    assert fake_bq.client.calls == [("list_rows", "bigquery-public-data.samples.shakespeare", 1000)]


def test_block_sample_falls_back_to_limit_when_short():
    """A small table's block sample can come back empty; LIMIT is cheap there."""
    con = ibis.duckdb.connect()
    con.con.execute("CREATE TABLE t AS SELECT range AS n FROM range(5)")
    t = metered.fetch_sample(con, "snowflake", None, "t", 3)
    assert t.num_rows == 3


def test_bigquery_partition_columns(fake_bq):
    assert metered.partition_columns(fake_bq, "bigquery", "ds", "t") == ["timestamp"]
    fake_bq.client.time_field = None  # ingestion-time partitioning
    assert metered.partition_columns(fake_bq, "bigquery", "ds", "t") == ["_PARTITIONTIME"]
    fake_bq.client.time_field, fake_bq.client.range_field = False, "id"
    assert metered.partition_columns(fake_bq, "bigquery", "ds", "t") == ["id"]
    assert metered.partition_columns(NS(), "snowflake", "ds", "t") == []


def test_bigquery_estimate_is_a_free_dry_run(fake_bq):
    assert metered.estimate_bytes(fake_bq, "bigquery", "SELECT 1") == 3_127_887_272_858
    (_, sql, cfg), = fake_bq.client.calls
    assert sql == "SELECT 1"
    assert cfg == {"dry_run": True, "use_query_cache": False}


def test_snowflake_estimate_reads_explain_json():
    class Cur:
        def fetchone(self):
            return ('{"GlobalStats": {"bytesAssigned": 4096, "partitionsTotal": 2}}',)

        def close(self):
            pass

    seen = []
    backend = NS(raw_sql=lambda sql: seen.append(sql) or Cur())
    assert metered.estimate_bytes(backend, "snowflake", "SELECT 1") == 4096
    assert seen == ["EXPLAIN USING JSON SELECT 1"]


def test_price_is_bigquery_on_demand_only():
    assert metered.est_cost_usd("bigquery", 2**40) == pytest.approx(6.25)
    assert metered.est_cost_usd("snowflake", 2**40) is None


def test_bigquery_cap_error_names_need_and_cap():
    # The message BigQuery returned for maximum_bytes_billed=1000 on shakespeare.
    e = Exception("500 Query exceeded limit for bytes billed: 1000. 10485760 or higher required.; "
                  "reason: bytesBilledLimitExceeded")
    msg = metered.cap_message(e)
    assert "10.0 MiB" in msg and "1000 B" in msg and "dte_max_bytes_billed" in msg
    sf = Exception("Statement reached its statement or warehouse timeout of 30 second(s) and was canceled.")
    assert "30s" in metered.cap_message(sf)
    assert metered.cap_message(Exception("syntax error")) is None


def test_a_cap_hit_inside_a_run_phase_is_a_clear_error():
    from dte.airflow.runner import _phase

    with pytest.raises(metered.QueryCapExceeded, match="cap"):
        with _phase(logging.getLogger("t"), lambda *a: None, "execute"):
            raise RuntimeError("Query exceeded limit for bytes billed: 1000. 10485760 or higher required.")


# ── load_interactive ─────────────────────────────────────────────────────


@pytest.fixture
def warehouse(monkeypatch):
    """A metered source whose 'warehouse' is a DuckDB table; counts fetches."""
    calls = []

    def fake_fetch(backend, kind, schema, table, n):
        calls.append((kind, schema, table, n))
        return pa.table({"word": ["a", "b"], "timestamp": [1, 2]})

    monkeypatch.setattr(metered, "fetch_sample", fake_fetch)
    monkeypatch.setattr(metered, "partition_columns", lambda *a: ["timestamp"])
    monkeypatch.setattr("dte.engine.backend_registry._open_ibis_backend", lambda c, cr: NS(name="bigquery"))
    return calls


def _interactive(table="shakespeare", **kw):
    reg = BackendRegistry(duckdb_con=ibis.duckdb.connect())
    return sample_mod.load_interactive(_bq_source(), reg, BQ, BQ.credentials, table=table,
                                       sample=1000, **kw).execute()


def test_metered_preview_reads_a_cached_sample(warehouse):
    assert list(_interactive()["word"]) == ["a", "b"]
    assert list(_interactive()["word"]) == ["a", "b"]
    assert warehouse == [("bigquery", "bigquery-public-data.samples", "shakespeare", 1000)]
    info = sample_mod.sample_info(_bq_source(), BQ, "shakespeare")
    assert info["rows"] == 2 and info["partition_columns"] == ["timestamp"] and info["taken_at"]


def test_each_table_gets_its_own_sample(warehouse):
    _interactive("a")
    _interactive("b")
    assert [c[2] for c in warehouse] == ["a", "b"]


def test_dropping_the_sample_refetches(warehouse):
    _interactive()
    assert sample_mod.drop_sample(_bq_source(), BQ, "shakespeare") is True
    _interactive()
    assert len(warehouse) == 2


def test_unmetered_sql_sources_still_push_down(warehouse, monkeypatch):
    pg = Connection(id="pg", connection_type="postgres", credentials={})
    seen = []
    monkeypatch.setattr(sample_mod, "load_source", lambda *a, **k: seen.append(k) or "live")
    reg = BackendRegistry(duckdb_con=ibis.duckdb.connect())
    assert sample_mod.load_interactive(_bq_source(), reg, pg, {}, table="t", sample=10) == "live"
    assert warehouse == []
    assert sample_mod.sample_info(_bq_source(), pg, "t") is None


def test_small_runs_need_no_confirmation():
    assert metered.judge("bigquery", 2**30, 2**30 / 2**40 * 6.25).needs_confirm is False
    small = metered.judge("snowflake", 50 * 2**20, None, warehouse="DTE_WH")
    assert small.needs_confirm is False
    assert small.message == "A small query: it reads about 50.0 MiB on the DTE_WH warehouse."
    # Unknown size: nothing to say, so nothing to ask.
    assert metered.judge("snowflake", None, None).needs_confirm is False


def test_bigquery_speaks_money():
    v = metered.judge("bigquery", 3 * 2**40, 18.75)
    assert v.needs_confirm and v.message == "This run will cost about $18.75 on BigQuery."


def test_snowflake_names_the_warehouse_and_the_time_limit():
    """Snowflake bills warehouse time, so bytes alone would mislead."""
    v = metered.judge("snowflake", 20 * 2**30, None, warehouse="DTE_WH", timeout_seconds=300)
    assert v.needs_confirm
    assert v.message == ("This is a large query: it reads about 20.0 GiB. Snowflake bills for every "
                         "minute the DTE_WH warehouse runs, and this connection stops a query after "
                         "5 minutes.")
    assert metered.judge("snowflake", 20 * 2**30, None).message.endswith(
        "and this connection sets no time limit.")


def test_the_threshold_comes_from_the_connection():
    assert metered.judge("snowflake", 50 * 2**20, None, confirm_above=2**20).needs_confirm
    assert not metered.judge("bigquery", 3 * 2**40, 18.75, confirm_above=4 * 2**40).needs_confirm


def test_a_run_over_the_cap_is_blocked_with_what_to_do():
    v = metered.judge("bigquery", 3 * 2**40, 18.75, cap=2**40)
    assert v.blocked and v.needs_confirm
    assert v.message == ("This run would read about 3.0 TiB, more than the 1.0 TiB this connection "
                         "allows, so BigQuery will refuse it. Add a filter so it reads less, or ask "
                         "an admin to raise the limit.")
