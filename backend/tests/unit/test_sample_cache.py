"""Interactive loads of eager sources read a cached parquet sample (plan 084).

The editor fires schema, step schemas and preview on open and on every edit;
without the cache each one re-downloads the source.
"""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import ibis
import pytest

from dte.engine.backend_registry import BackendRegistry
from dte.models.pipeline import Connection, Source
from dte.sources import sample as sample_mod
from dte.sources.sample import load_interactive, sample_path

CONN = Connection(id="local_fs", connection_type="local_fs", credentials={})


def _rest(**config) -> Source:
    return Source(
        id="r", connection_id="local_fs", source_type="rest_api", table="items",
        config={"client": {"base_url": "http://x/"}, "resources": ["items"], **config},
    )


@pytest.fixture
def fake_loader(monkeypatch):
    """Stands in for a slow REST fetch; counts how often it runs."""
    calls = []
    lock = threading.Lock()

    def fake(source, registry, connection, credentials, table=None, sample=None):
        with lock:
            calls.append(sample)
        time.sleep(0.2)
        con = registry.duckdb()
        con.con.execute("CREATE OR REPLACE TABLE fetched AS SELECT range AS n FROM range(5)")
        return con.table("fetched")

    monkeypatch.setattr(sample_mod, "load_source", fake)
    return calls


def _load(source, sample=3):
    registry = BackendRegistry(duckdb_con=ibis.duckdb.connect())
    return load_interactive(source, registry, CONN, {}, sample=sample).execute()


def test_miss_fetches_with_sample_then_hit_reads_the_parquet(fake_loader):
    assert len(_load(_rest())) == 5
    assert fake_loader == [3]
    assert len(_load(_rest())) == 5
    assert fake_loader == [3]
    assert str(sample_path(_rest(), CONN)).startswith(os.environ["DTE_ARTIFACT_DIR"])


def test_concurrent_misses_fetch_once(fake_loader):
    with ThreadPoolExecutor(6) as pool:
        sizes = list(pool.map(lambda _: len(_load(_rest())), range(6)))
    assert sizes == [5] * 6
    assert len(fake_loader) == 1


def test_config_change_is_a_new_key(fake_loader):
    _load(_rest())
    _load(_rest(extra="changed"))
    assert len(fake_loader) == 2
    assert sample_path(_rest(), CONN) != sample_path(_rest(extra="changed"), CONN)


def test_stale_sample_is_refetched(fake_loader, monkeypatch):
    _load(_rest())
    old = time.time() - 100
    os.utime(sample_path(_rest(), CONN), (old, old))
    monkeypatch.setenv("DTE_SAMPLE_TTL_SECONDS", "50")
    _load(_rest())
    assert len(fake_loader) == 2


def test_view_keeps_the_dlt_dataset_schema(fake_loader):
    """Pipelines reference eager sources as `dte_sources.<table>` in raw SQL
    (pypi_squat_scan does); a cached sample must answer to the same name."""
    con = ibis.duckdb.connect()
    load_interactive(_rest(), BackendRegistry(duckdb_con=con), CONN, {}, sample=3)
    assert con.con.execute("SELECT count(*) FROM dte_sources.items").fetchone() == (5,)


def test_lazy_sources_bypass_the_cache(tmp_path, fake_loader):
    (tmp_path / "a.json").write_text(json.dumps([{"x": 1}]))
    src = Source(
        id="f", connection_id="local_fs", source_type="filesystem", table="f",
        config={"bucket_url": str(tmp_path), "file_glob": "a.json"},
    )
    _load(src)
    assert len(fake_loader) == 1  # the (patched) loader ran directly
    assert not (tmp_path.parent / "artifacts" / "samples").exists() or not any(
        (tmp_path.parent / "artifacts" / "samples").iterdir()
    )
