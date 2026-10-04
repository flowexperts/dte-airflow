from types import SimpleNamespace as NS

import pytest

from dte.airflow.connections import from_airflow


def c(conn_type, **kw):
    d = dict(conn_id="c", conn_type=conn_type, host=None, schema=None, login=None, password=None, port=None, extra_dejson={})
    d.update(kw)
    return NS(**d)


CASES = [
    (c("postgres", host="h", port=5432, schema="db", login="u", password="p@"), "postgres", {"url": "postgresql://u:p%40@h:5432/db"}),
    (c("mysql", host="h", schema="db", login="u", password="p"), "mysql", {"url": "mysql://u:p@h/db"}),
    (c("mssql", host="h", port=1433, schema="db", login="sa", password="p", extra_dejson={"TrustServerCertificate": "yes"}), "mssql", {"url": "mssql://sa:p@h:1433/db?TrustServerCertificate=yes"}),
    (c("sqlite", host="/x.db"), "sqlite", {"url": "sqlite:////x.db"}),
    (c("snowflake", login="u", password="p", schema="s", extra_dejson={"account": "acc", "warehouse": "w"}), "snowflake", {"url": "snowflake://u:p@acc/s?warehouse=w"}),
    (c("mongo", host="h", login="u", password="p"), "mongodb", {"url": "mongodb://u:p@h/"}),
    (c("google_cloud_platform", extra_dejson={"project": "prj"}), "bigquery", {"url": "bigquery://prj"}),
    (c("google_cloud_platform", extra_dejson={"hmac_key_id": "k", "hmac_secret": "s"}), "gcs", {"hmac_key_id": "k", "hmac_secret": "s"}),
    (c("aws", login="a", password="b", extra_dejson={"region_name": "r"}), "s3", {"aws_access_key_id": "a", "aws_secret_access_key": "b", "region_name": "r"}),
    (c("wasb", login="acct", password="key"), "azure", {"azure_storage_account_name": "acct", "azure_storage_account_key": "key"}),
    (c("http", password="tok"), "rest_api", {"auth": {"type": "bearer", "token": "tok"}, "headers": {}}),
    (c("fs"), "local_fs", {}),
]


@pytest.mark.parametrize("conn,kind,creds", CASES, ids=[k[1] + str(i) for i, k in enumerate(CASES)])
def test_mapping(conn, kind, creds):
    out = from_airflow(conn)
    assert (out.connection_type, out.credentials) == (kind, creds)


def test_unknown_type():
    with pytest.raises(ValueError):
        from_airflow(c("redis"))
