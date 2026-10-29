"""Object storage goes through the provider's fsspec filesystem (plan 074)."""
import json

import duckdb
import fsspec
import pytest

from dte.sources import object_store


@pytest.fixture
def bucket(monkeypatch):
    fs = fsspec.filesystem("memory", skip_instance_cache=True)
    fs.store.clear()
    fs.pipe("/b/in/a.json", json.dumps([{"id": 1}, {"id": 2}]).encode())
    fs.pipe("/b/in/sub/c.json", json.dumps([{"id": 3}]).encode())
    seen = []

    def provider_fs(url, conn_id):
        seen.append((url, conn_id))
        return fs

    monkeypatch.setattr(object_store, "_provider_fs", provider_fs)
    return fs, seen


def test_reads_through_the_connections_filesystem(bucket):
    _, seen = bucket
    con = duckdb.connect()
    url = object_store.register(con, "s3://b/in/**/*.json", "aws_prod")
    assert url == "dte_s3_aws_prod://b/in/**/*.json"
    assert con.execute(f"select count(*) from read_json_auto('{url}')").fetchone() == (3,)
    assert seen == [("s3://b/in/**/*.json", "aws_prod")]


def test_writes_through_the_connections_filesystem(bucket):
    fs, _ = bucket
    con = duckdb.connect()
    url = object_store.register(con, "s3://b/out/o.parquet", "aws_prod")
    con.execute(f"COPY (select 42 as x) TO '{url}' (FORMAT parquet)")
    assert fs.exists("/b/out/o.parquet")


def test_two_connections_coexist_and_reregistering_is_fine(bucket):
    con = duckdb.connect()
    a = object_store.register(con, "s3://b/in/a.json", "aws-prod.eu")
    b = object_store.register(con, "s3://b/in/a.json", "other")
    object_store.register(con, "s3://b/in/a.json", "other")
    assert a.startswith("dte_s3_aws_prod_eu://")
    q = f"select count(*) from read_json_auto('{a}') x, read_json_auto('{b}') y"
    assert con.execute(q).fetchone() == (4,)


@pytest.mark.parametrize("url", ["/tmp/x.json", "file:///tmp/x.json", "relative/x.json"])
def test_local_paths_untouched(url):
    assert object_store.register(duckdb.connect(), url, "fs_default") == url


def test_legacy_schemes_reach_the_provider_scheme(bucket):
    _, seen = bucket
    con = duckdb.connect()
    object_store.register(con, "gcs://b/in/a.json", "g")
    object_store.register(con, "az://b/in/a.json", "w")
    assert [u for u, _ in seen] == ["gs://b/in/a.json", "abfs://b/in/a.json"]
