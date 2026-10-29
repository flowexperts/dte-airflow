"""Airflow Connection -> DTE: the installed provider does the auth (plan 074)."""
from types import SimpleNamespace as NS

import pytest

from dte.airflow import connections
from dte.airflow.connections import available_kinds, from_airflow


class _Url:
    """Stands in for sqlalchemy.engine.URL."""

    def __init__(self, s):
        self.s = s

    def render_as_string(self, hide_password=True):
        return self.s


def c(conn_type, hook=None, **kw):
    d = dict(conn_id="c", conn_type=conn_type, host=None, schema=None, login=None,
             password=None, port=None, extra_dejson={})
    d.update(kw)
    return NS(**d, get_hook=lambda: hook)


SQL = [
    ("postgres", NS(sqlalchemy_url=_Url("postgresql+psycopg2://u:p%40@h:5432/db")), "postgresql://u:p%40@h:5432/db"),
    ("mysql", NS(sqlalchemy_url=_Url("mysql+mysqldb://u:p@h/db")), "mysql://u:p@h/db"),
    ("mssql", NS(get_uri=lambda: "mssql+pymssql://sa:p@h:1433/db?TrustServerCertificate=yes"),
     "mssql://sa:p@h:1433/db?TrustServerCertificate=yes"),
    ("sqlite", NS(get_uri=lambda: "sqlite:////x.db"), "sqlite:////x.db"),
    ("snowflake", NS(get_uri=lambda: "snowflake://u:p@acc/s?warehouse=w"), "snowflake://u:p@acc/s?warehouse=w"),
]


@pytest.mark.parametrize("conn_type,hook,url", SQL, ids=[s[0] for s in SQL])
def test_sql_url_comes_from_the_provider_hook(conn_type, hook, url):
    out = from_airflow(c(conn_type, hook))
    assert (out.connection_type, out.credentials) == (conn_type, {"url": url})


def test_sqlalchemy_url_falls_back_to_get_uri():
    class Hook:
        @property
        def sqlalchemy_url(self):
            raise NotImplementedError

        def get_uri(self):
            return "postgresql://u:p@h/db"

    assert from_airflow(c("postgres", Hook())).credentials == {"url": "postgresql://u:p@h/db"}


def test_mongo_uri_from_hook():
    out = from_airflow(c("mongo", NS(uri="mongodb://u:p@h/")))
    assert (out.connection_type, out.credentials) == ("mongodb", {"url": "mongodb://u:p@h/"})


@pytest.mark.parametrize("conn_type,kind", [
    ("aws", "s3"), ("google_cloud_platform", "gcs"), ("wasb", "azure"), ("adls", "azure"),
    ("azure_data_lake", "azure"), ("sftp", "sftp"),
])
def test_storage_connections_carry_only_the_conn_id(conn_type, kind):
    out = from_airflow(c(conn_type, conn_id="prod"))
    assert (out.id, out.connection_type, out.credentials) == ("prod", kind, {"conn_id": "prod"})


def test_gcp_with_bigquery_dte_type():
    out = from_airflow(c("google_cloud_platform", NS(project_id="prj"), extra_dejson={"dte_type": "bigquery"}))
    assert (out.connection_type, out.credentials) == ("bigquery", {"url": "bigquery://prj", "conn_id": "c"})


def test_the_google_providers_bigquery_conn_type_maps_to_bigquery():
    out = from_airflow(c("gcpbigquery", NS(project_id="prj")))
    assert (out.connection_type, out.credentials) == ("bigquery", {"url": "bigquery://prj", "conn_id": "c"})


def test_http_and_fs_unchanged():
    assert from_airflow(c("http", password="tok")).credentials == {
        "auth": {"type": "bearer", "token": "tok"}, "headers": {}}
    assert from_airflow(c("fs")).connection_type == "local_fs"


def test_unknown_type():
    with pytest.raises(ValueError):
        from_airflow(c("redis"))


def test_kinds_follow_installed_providers(monkeypatch):
    monkeypatch.setattr(connections, "_installed", lambda: ({"fs", "postgres", "aws"}, {"s3"}))
    kinds = available_kinds()
    assert {"local_fs", "postgres", "s3"} <= kinds
    assert not kinds & {"mongodb", "mssql", "gcs", "azure", "sftp"}


def test_storage_kind_needs_the_provider_filesystem(monkeypatch):
    # amazon provider installed but its s3 filesystem (s3fs) isn't.
    monkeypatch.setattr(connections, "_installed", lambda: ({"aws"}, set()))
    assert "s3" not in available_kinds()
