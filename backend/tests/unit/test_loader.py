import pytest
import json
import ibis
from dte.models.pipeline import Source
from dte.sources.loader import load_source


def test_load_local_json_via_dlt(tmp_path):
    data = [{"name": "alice", "age": 30}, {"name": "bob", "age": 25}]
    f = tmp_path / "input.json"
    f.write_text(json.dumps(data))

    src = Source(
        id="s1",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "input.json"},
        table="input",
    )
    con = ibis.duckdb.connect()
    result = load_source(src, con)

    df = result.execute()
    assert set(df.columns).issuperset({"name", "age"})
    assert len(df) == 2
    names = sorted(df["name"].tolist())
    assert names == ["alice", "bob"]


def test_load_jsonl_nested_as_struct(tmp_path):
    lines = [
        {"id": "o1", "order": {"amount": 100, "currency": "USD"}},
        {"id": "o2", "order": {"amount": 42, "currency": "EUR"}},
        {"id": "o3", "order": {"amount": 7, "currency": "USD"}},
    ]
    f = tmp_path / "orders.jsonl"
    f.write_text("\n".join(json.dumps(l) for l in lines) + "\n")

    src = Source(
        id="s_jsonl",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "*.jsonl"},
        table="orders",
    )
    con = ibis.duckdb.connect()
    table = load_source(src, con)

    # DuckDB native readers expose nested JSON as STRUCT columns.
    schema = table.schema()
    assert "order" in schema.names
    assert str(schema["order"]).startswith("struct")

    df = table.execute()
    assert len(df) == 3
    assert sorted(df["id"].tolist()) == ["o1", "o2", "o3"]


def test_load_csv(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("id,name,age\n1,alice,30\n2,bob,25\n")

    src = Source(
        id="s_csv",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "*.csv"},
        table="people",
    )
    con = ibis.duckdb.connect()
    df = load_source(src, con).execute()
    assert sorted(df["name"].tolist()) == ["alice", "bob"]


def test_load_parquet(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    tbl = pa.table({"id": [1, 2], "name": ["alice", "bob"]})
    pq.write_table(tbl, str(tmp_path / "data.parquet"))

    src = Source(
        id="s_parq",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "*.parquet"},
        table="people",
    )
    con = ibis.duckdb.connect()
    df = load_source(src, con).execute()
    assert sorted(df["name"].tolist()) == ["alice", "bob"]


def test_load_jsonl_ignores_blank_lines(tmp_path):
    f = tmp_path / "orders.jsonl"
    f.write_text('{"id": "a"}\n\n{"id": "b"}\n   \n')

    src = Source(
        id="s_blank",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "*.jsonl"},
        table="orders",
    )
    con = ibis.duckdb.connect()
    df = load_source(src, con).execute()
    assert sorted(df["id"].tolist()) == ["a", "b"]


def test_load_explicit_format_overrides_extension(tmp_path):
    # File named .json but is really NDJSON — explicit format wins.
    f = tmp_path / "wrong-ext.json"
    f.write_text('{"id": "x"}\n{"id": "y"}\n')

    src = Source(
        id="s_fmt",
        source_type="filesystem",
        config={
            "bucket_url": str(tmp_path),
            "file_glob": "*.json",
            "format": "jsonl",
        },
        table="orders",
    )
    con = ibis.duckdb.connect()
    df = load_source(src, con).execute()
    assert sorted(df["id"].tolist()) == ["x", "y"]


def test_load_returns_ibis_table(tmp_path):
    data = [{"x": 1}]
    f = tmp_path / "data.json"
    f.write_text(json.dumps(data))

    src = Source(
        id="s2",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "data.json"},
        table="data",
    )
    con = ibis.duckdb.connect()
    result = load_source(src, con)
    assert isinstance(result, ibis.Table)


def test_missing_file_raises(tmp_path):
    src = Source(
        id="s3",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path / "nonexistent"), "file_glob": "*.json"},
        table="missing",
    )
    con = ibis.duckdb.connect()
    with pytest.raises(Exception):
        load_source(src, con)


def test_unknown_source_type_raises():
    src = Source(
        id="s4",
        source_type="nonesuch",
        config={},
        table="t",
    )
    con = ibis.duckdb.connect()
    with pytest.raises(NotImplementedError, match="nonesuch"):
        load_source(src, con)


def test_resolve_secret_returns_literal():
    from dte.sources.loader import resolve_secret
    assert resolve_secret("literal") == "literal"


def test_resolve_secret_reads_env(monkeypatch):
    from dte.sources.loader import resolve_secret
    monkeypatch.setenv("DTE_TEST_SECRET", "shhh")
    assert resolve_secret({"env": "DTE_TEST_SECRET"}) == "shhh"


def test_resolve_secret_missing_env_raises(monkeypatch):
    from dte.sources.loader import resolve_secret
    monkeypatch.delenv("DTE_TEST_MISSING", raising=False)
    with pytest.raises(KeyError, match="DTE_TEST_MISSING"):
        resolve_secret({"env": "DTE_TEST_MISSING"})


def test_s3_secret_sql_from_config():
    from dte.sources.loader import _build_s3_secret_sql
    sql = _build_s3_secret_sql({
        "aws_access_key_id": "AKIA",
        "aws_secret_access_key": "sekret",
        "region_name": "us-east-1",
    }, secret_name="dte_src_s5_s3")
    assert 'CREATE OR REPLACE SECRET "dte_src_s5_s3"' in sql
    assert "TYPE s3" in sql
    assert "KEY_ID 'AKIA'" in sql
    assert "SECRET 'sekret'" in sql
    assert "REGION 'us-east-1'" in sql


def test_s3_secret_sql_resolves_env_secrets(monkeypatch):
    from dte.sources.loader import _build_s3_secret_sql
    monkeypatch.setenv("MY_AWS_KEY", "AKIAENV")
    monkeypatch.setenv("MY_AWS_SECRET", "envsekret")
    sql = _build_s3_secret_sql({
        "aws_access_key_id": {"env": "MY_AWS_KEY"},
        "aws_secret_access_key": {"env": "MY_AWS_SECRET"},
    }, secret_name="s")
    assert "KEY_ID 'AKIAENV'" in sql
    assert "SECRET 'envsekret'" in sql


def test_s3_secret_sql_http_endpoint_disables_ssl_and_uses_path_style():
    from dte.sources.loader import _build_s3_secret_sql
    sql = _build_s3_secret_sql({
        "endpoint_url": "http://localhost:4566",
    }, secret_name="s")
    assert "ENDPOINT 'localhost:4566'" in sql
    assert "URL_STYLE 'path'" in sql
    assert "USE_SSL false" in sql


def test_s3_secret_sql_https_endpoint_keeps_ssl():
    from dte.sources.loader import _build_s3_secret_sql
    sql = _build_s3_secret_sql({
        "endpoint_url": "https://custom.s3-endpoint.example",
    }, secret_name="s")
    assert "ENDPOINT 'custom.s3-endpoint.example'" in sql
    assert "USE_SSL" not in sql


def test_gcs_secret_sql_hmac_keys():
    from dte.sources.loader import _build_gcs_secret_sql
    sql = _build_gcs_secret_sql({
        "hmac_key_id": "GOOGKEY",
        "hmac_secret": "gsecret",
    }, secret_name="g")
    assert "TYPE gcs" in sql
    assert "KEY_ID 'GOOGKEY'" in sql
    assert "SECRET 'gsecret'" in sql


def test_gcs_secret_sql_env_indirection(monkeypatch):
    from dte.sources.loader import _build_gcs_secret_sql
    monkeypatch.setenv("GCS_HMAC_ID", "GK")
    monkeypatch.setenv("GCS_HMAC_SECRET", "GS")
    sql = _build_gcs_secret_sql({
        "hmac_key_id": {"env": "GCS_HMAC_ID"},
        "hmac_secret": {"env": "GCS_HMAC_SECRET"},
    }, secret_name="g")
    assert "KEY_ID 'GK'" in sql
    assert "SECRET 'GS'" in sql


def test_gcs_credentials_json_no_longer_accepted():
    from dte.sources.loader import _build_gcs_secret_sql
    with pytest.raises(ValueError, match="HMAC"):
        _build_gcs_secret_sql({
            "credentials_json": {"type": "service_account"},
        }, secret_name="g")


def test_azure_secret_sql_connection_string():
    from dte.sources.loader import _build_azure_secret_sql
    sql = _build_azure_secret_sql({
        "connection_string": "DefaultEndpointsProtocol=https;AccountName=a;AccountKey=k;",
    }, secret_name="az")
    assert "TYPE azure" in sql
    assert "CONNECTION_STRING 'DefaultEndpointsProtocol=https;AccountName=a;AccountKey=k;'" in sql


def test_azure_secret_sql_account_name_and_key():
    from dte.sources.loader import _build_azure_secret_sql
    sql = _build_azure_secret_sql({
        "account_name": "myacct",
        "account_key": "mykey",
    }, secret_name="az")
    assert "ACCOUNT_NAME 'myacct'" in sql
    assert "ACCOUNT_KEY 'mykey'" in sql


def test_azure_secret_sql_env_indirection(monkeypatch):
    from dte.sources.loader import _build_azure_secret_sql
    monkeypatch.setenv("AZ_CONN", "DefaultEndpointsProtocol=https;AccountName=x;AccountKey=y;")
    sql = _build_azure_secret_sql({
        "connection_string": {"env": "AZ_CONN"},
    }, secret_name="az")
    assert "AccountName=x" in sql


def test_azure_secret_sql_missing_credentials_raises():
    from dte.sources.loader import _build_azure_secret_sql
    with pytest.raises(ValueError, match="credentials"):
        _build_azure_secret_sql({}, secret_name="az")


def test_dispatch_registers_object_storage_types():
    from dte.sources.loader import LOADERS
    assert "s3" in LOADERS
    assert "gcs" in LOADERS
    assert "azure" in LOADERS


def test_secret_sql_escapes_single_quotes():
    """Secrets containing a `'` must be escaped so they don't break the DDL."""
    from dte.sources.loader import _build_s3_secret_sql
    sql = _build_s3_secret_sql({
        "aws_access_key_id": "AK",
        "aws_secret_access_key": "has'quote",
    }, secret_name="s")
    assert "SECRET 'has''quote'" in sql


def test_sql_database_loader_end_to_end(tmp_path):
    """Load a table from a SQLite database via dlt sql_database source."""
    import sqlite3
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE customers (id INTEGER, name TEXT, age INTEGER)")
    conn.executemany(
        "INSERT INTO customers VALUES (?, ?, ?)",
        [(1, "alice", 30), (2, "bob", 25), (3, "carol", 35)],
    )
    conn.commit()
    conn.close()

    src = Source(
        id="sql1",
        source_type="sql_database",
        config={
            "credentials": f"sqlite:///{db_path}",
            "table": "customers",
        },
        table="customers_out",
    )
    con = ibis.duckdb.connect()
    result = load_source(src, con)
    df = result.execute()
    assert len(df) == 3
    assert set(df.columns).issuperset({"id", "name", "age"})
    assert sorted(df["name"].tolist()) == ["alice", "bob", "carol"]


def test_sql_database_credentials_resolved_from_env(monkeypatch, tmp_path):
    """`credentials` may be an env-indirection."""
    import sqlite3
    db_path = tmp_path / "envtest.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()

    monkeypatch.setenv("DTE_SQL_DSN", f"sqlite:///{db_path}")
    src = Source(
        id="sql2",
        source_type="sql_database",
        config={"credentials": {"env": "DTE_SQL_DSN"}, "table": "t"},
        table="t_out",
    )
    con = ibis.duckdb.connect()
    result = load_source(src, con)
    df = result.execute()
    assert df["x"].tolist() == [42]


def test_dispatch_registers_sql_database():
    from dte.sources.loader import LOADERS
    assert "sql_database" in LOADERS


def test_sql_database_unsupported_scheme_raises():
    src = Source(
        id="sql_bad",
        source_type="sql_database",
        config={"credentials": "snowflake://user:pw@acct", "table": "t"},
        table="t",
    )
    con = ibis.duckdb.connect()
    with pytest.raises(NotImplementedError, match="snowflake"):
        load_source(src, con)


def test_mongodb_loader_end_to_end(monkeypatch):
    """Load documents from a mongomock-backed MongoDB collection."""
    import mongomock
    from dte.sources import loader as dlt_loader

    mock_client = mongomock.MongoClient()
    mock_client["mydb"]["mycoll"].insert_many([
        {"name": "alice", "score": 10},
        {"name": "bob", "score": 20},
        {"name": "carol", "score": 30},
    ])

    monkeypatch.setattr(dlt_loader, "_mongo_client", lambda url: mock_client)

    src = Source(
        id="mongo1",
        source_type="mongodb",
        config={
            "connection_url": "mongodb://ignored",
            "database": "mydb",
            "collection": "mycoll",
        },
        table="mongo_out",
    )
    con = ibis.duckdb.connect()
    result = load_source(src, con)
    df = result.execute()
    assert len(df) == 3
    assert sorted(df["name"].tolist()) == ["alice", "bob", "carol"]


def test_mongodb_connection_url_from_env(monkeypatch):
    import mongomock
    from dte.sources import loader as dlt_loader

    mock_client = mongomock.MongoClient()
    mock_client["d"]["c"].insert_one({"x": 1})

    captured = {}

    def fake_client(url):
        captured["url"] = url
        return mock_client

    monkeypatch.setenv("DTE_MONGO_URL", "mongodb://prod-host:27017")
    monkeypatch.setattr(dlt_loader, "_mongo_client", fake_client)

    src = Source(
        id="mongo2",
        source_type="mongodb",
        config={
            "connection_url": {"env": "DTE_MONGO_URL"},
            "database": "d",
            "collection": "c",
        },
        table="m2",
    )
    con = ibis.duckdb.connect()
    load_source(src, con)
    assert captured["url"] == "mongodb://prod-host:27017"


def test_dispatch_registers_mongodb():
    from dte.sources.loader import LOADERS
    assert "mongodb" in LOADERS


def test_rest_api_loader_end_to_end(monkeypatch):
    """Load a REST API resource via dlt's rest_api source with a mocked HTTP layer."""
    import requests_mock

    with requests_mock.Mocker() as m:
        m.get(
            "https://api.example.com/items",
            json=[
                {"id": 1, "title": "one"},
                {"id": 2, "title": "two"},
            ],
        )

        src = Source(
            id="rest1",
            source_type="rest_api",
            config={
                "client": {"base_url": "https://api.example.com/"},
                "resources": [
                    {
                        "name": "items",
                        "endpoint": {"path": "items", "paginator": "single_page"},
                    }
                ],
            },
            table="items",
        )
        con = ibis.duckdb.connect()
        result = load_source(src, con)
        df = result.execute()

    assert len(df) == 2
    assert set(df.columns).issuperset({"id", "title"})
    assert sorted(df["title"].tolist()) == ["one", "two"]


def test_rest_api_resource_name_overridden_to_source_table(monkeypatch):
    """The loader materialises the result under source.table regardless of the
    resource name in config."""
    import requests_mock

    with requests_mock.Mocker() as m:
        m.get(
            "https://api.example.com/things",
            json=[{"x": 1}],
        )
        src = Source(
            id="rest2",
            source_type="rest_api",
            config={
                "client": {"base_url": "https://api.example.com/"},
                "resources": [
                    {
                        "name": "things",
                        "endpoint": {"path": "things", "paginator": "single_page"},
                    }
                ],
            },
            table="renamed_output",
        )
        con = ibis.duckdb.connect()
        result = load_source(src, con)
        df = result.execute()
    assert len(df) == 1
    assert df["x"].tolist() == [1]


def test_dispatch_registers_rest_api():
    from dte.sources.loader import LOADERS
    assert "rest_api" in LOADERS
