"""Plan 089: every pipeline's `run` task declares Assets for lineage."""
from types import SimpleNamespace as NS

import pytest

from dte.airflow.assets import asset_uri, lineage
from dte.airflow.dag_factory import _dag_for
from dte.models.pipeline import Destination, Source, SourceTableRef


def _dest(cfg, conn="wh"):
    return Destination(id="d1", connection_id=conn, config=cfg, dest_type=cfg["type"]).narrow_config()


def _src(kind, cfg, conn="lake"):
    return Source(id="s1", connection_id=conn, source_type=kind, config=cfg, table="t")


@pytest.mark.parametrize("cfg, uri", [
    ({"type": "postgres", "schema": "mart", "table": "orders"}, "dte://wh/mart/orders"),
    ({"type": "sql_database", "dialect": "snowflake", "schema": "mart", "table": "orders"}, "dte://wh/mart/orders"),
    ({"type": "json", "path": "/data/out/orders.json"}, "file:///data/out/orders.json"),
    ({"type": "csv", "path": "out/orders.csv"}, "file:///out/orders.csv"),
    ({"type": "excel", "path": "/data/orders.xlsx"}, "file:///data/orders.xlsx"),
    ({"type": "parquet", "path": "s3://bucket/out/orders.parquet"}, "s3://bucket/out/orders.parquet"),
])
def test_destination_uri(cfg, uri):
    assert asset_uri(_dest(cfg)) == uri


@pytest.mark.parametrize("kind, cfg, table, uri", [
    ("sql_database", {"schema": "mart"}, "orders", "dte://lake/mart/orders"),
    ("sql_database", {}, "orders", "dte://lake/default/orders"),
    ("filesystem", {"bucket_url": "/data/in", "file_glob": "orders.json"}, None, "file:///data/in/orders.json"),
    ("s3", {"bucket_url": "s3://bucket/out/", "file_glob": "*.parquet"}, None, "s3://bucket/out/*.parquet"),
    ("gcs", {"bucket_url": "gs://b/in", "file_glob": "a.csv"}, None, "gs://b/in/a.csv"),
    ("azure", {"bucket_url": "az://c/in", "file_glob": "a.csv"}, None, "az://c/in/a.csv"),
    ("sftp", {"bucket_url": "sftp://host/in", "file_glob": "a.csv"}, None, "sftp://host/in/a.csv"),
    ("documents", {"bucket_url": "/docs", "file_glob": "**/*.pdf"}, None, "file:///docs/**/*.pdf"),
    ("mongodb", {"database": "app", "collection": "users"}, None, "dte://lake/app/users"),
    ("rest_api", {"client": {"base_url": "https://api.example.com"}}, None, None),
])
def test_source_uri(kind, cfg, table, uri):
    assert asset_uri(_src(kind, cfg), table) == uri


def test_uri_never_carries_credentials():
    src = _src("sftp", {"bucket_url": "sftp://bob:hunter2@host/in", "file_glob": "a.csv"})
    assert asset_uri(src) == "sftp://host/in/a.csv"


def test_db_destination_and_source_on_same_conn_share_a_uri():
    """The point of lineage: A's output is B's input."""
    out = _dest({"type": "postgres", "schema": "mart", "table": "orders"}, conn="pg")
    inp = _src("sql_database", {"schema": "mart"}, conn="pg")
    assert asset_uri(out) == asset_uri(inp, "orders")


def _rev(config):
    return NS(id="r1", pipeline_id="p1", config={"name": "P", **config})


def test_lineage_reads_sources_and_destination():
    srcs = {"s1": _src("sql_database", {"schema": "raw"}, conn="pg")}
    dests = {"d1": _dest({"type": "json", "path": "/out/a.json"})}
    cfg = {"sources": [SourceTableRef(source_id="s1", table="orders", alias="o").model_dump()], "output_id": "d1"}
    assert lineage(cfg, srcs, dests) == (["dte://pg/raw/orders"], ["file:///out/a.json"])


def test_lineage_skips_missing_and_non_transform():
    cfg = {"sources": ["gone"], "output_id": "d1", "pipeline_type": "quality"}
    dests = {"d1": _dest({"type": "json", "path": "/out/a.json"})}
    assert lineage(cfg, {}, dests) == ([], [])


def test_dag_task_declares_inlets_and_outlets():
    task = _dag_for(_rev({}), inlets=["dte://pg/raw/orders"], outlets=["file:///out/a.json"]).get_task("run")
    assert [a.uri for a in task.inlets] == ["dte://pg/raw/orders"]
    assert [a.uri for a in task.outlets] == ["file:///out/a.json"]


def test_dag_without_lineage_has_no_assets():
    task = _dag_for(_rev({})).get_task("run")
    assert task.inlets == [] and task.outlets == []
