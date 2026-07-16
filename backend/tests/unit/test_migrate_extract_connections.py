from tests.fakes import FakeSourceStore, FakeDestinationStore, FakeConnectionStore
from scripts.migrate_extract_connections import (
    _migrate_source, _migrate_destination, LOCAL_FS_DEFAULT_ID,
)


async def test_filesystem_source_gets_local_fs_default():
    c_store = FakeConnectionStore()
    src = {
        "id": "s1", "source_type": "filesystem",
        "config": {"bucket_url": "/tmp"}, "table": "t",
    }
    updated, changed = await _migrate_source(src, c_store, log=[])
    assert changed
    assert updated["connection_id"] == LOCAL_FS_DEFAULT_ID
    assert "bucket_url" in updated["config"]
    conn = await c_store.get(LOCAL_FS_DEFAULT_ID)
    assert conn.connection_type == "local_fs"


async def test_s3_source_creds_extract_and_dedup():
    c_store = FakeConnectionStore()
    src_a = {
        "id": "sa", "source_type": "s3",
        "config": {
            "bucket_url": "s3://a/",
            "aws_access_key_id": "K", "aws_secret_access_key": "S", "region_name": "us-east-1",
        },
        "table": "a",
    }
    src_b = {
        "id": "sb", "source_type": "s3",
        "config": {
            "bucket_url": "s3://b/",
            "aws_access_key_id": "K", "aws_secret_access_key": "S", "region_name": "us-east-1",
        },
        "table": "b",
    }
    ua, _ = await _migrate_source(src_a, c_store, log=[])
    ub, _ = await _migrate_source(src_b, c_store, log=[])
    # Same creds → same connection.
    assert ua["connection_id"] == ub["connection_id"]
    # Creds no longer in config.
    for k in ("aws_access_key_id", "aws_secret_access_key", "region_name"):
        assert k not in ua["config"]
    # Non-cred config kept.
    assert ua["config"]["bucket_url"] == "s3://a/"


async def test_sql_database_source_url_refines_connection_type():
    c_store = FakeConnectionStore()
    src = {
        "id": "s1", "source_type": "sql_database",
        "config": {"credentials": "postgres://u:p@h/d", "table": "t"},
        "table": "t",
    }
    updated, _ = await _migrate_source(src, c_store, log=[])
    conn = await c_store.get(updated["connection_id"])
    assert conn.connection_type == "postgres"
    assert conn.credentials_dict()["url"] == "postgres://u:p@h/d"
    assert "credentials" not in updated["config"]


async def test_azure_source_normalizes_legacy_field_names():
    c_store = FakeConnectionStore()
    src = {
        "id": "s1", "source_type": "azure",
        "config": {
            "bucket_url": "az://container/",
            "account_name": "acct", "account_key": "k",
        },
        "table": "t",
    }
    updated, _ = await _migrate_source(src, c_store, log=[])
    conn = await c_store.get(updated["connection_id"])
    # Legacy names rewritten to dlt-aligned.
    assert conn.credentials_dict()["azure_storage_account_name"] == "acct"
    assert conn.credentials_dict()["azure_storage_account_key"] == "k"


async def test_mongodb_source_extracts_url():
    c_store = FakeConnectionStore()
    src = {
        "id": "s1", "source_type": "mongodb",
        "config": {
            "connection_url": "mongodb://u:p@h/d",
            "database": "d", "collection": "c",
        },
        "table": "t",
    }
    updated, _ = await _migrate_source(src, c_store, log=[])
    conn = await c_store.get(updated["connection_id"])
    assert conn.connection_type == "mongodb"
    assert conn.credentials_dict()["url"] == "mongodb://u:p@h/d"
    assert "connection_url" not in updated["config"]


async def test_json_file_destination_gets_local_fs_default():
    c_store = FakeConnectionStore()
    dest = {"id": "d1", "config": {"type": "json_file", "path": "/tmp/out.json"}}
    updated, changed = await _migrate_destination(dest, c_store, log=[])
    assert changed
    assert updated["connection_id"] == LOCAL_FS_DEFAULT_ID


async def test_postgres_destination_extracts_credentials():
    c_store = FakeConnectionStore()
    dest = {
        "id": "d1",
        "config": {
            "type": "postgres", "credentials": "postgres://u:p@h/d",
            "schema": "public", "table": "t",
        },
    }
    updated, _ = await _migrate_destination(dest, c_store, log=[])
    conn = await c_store.get(updated["connection_id"])
    assert conn.connection_type == "postgres"
    assert conn.credentials_dict()["url"] == "postgres://u:p@h/d"
    assert "credentials" not in updated["config"]


async def test_sql_database_destination_refines_type_by_dialect():
    c_store = FakeConnectionStore()
    dest = {
        "id": "d1",
        "config": {
            "type": "sql_database", "dialect": "snowflake",
            "credentials": "snowflake://u:p@acct/db",
            "schema": "public", "table": "t",
        },
    }
    updated, _ = await _migrate_destination(dest, c_store, log=[])
    conn = await c_store.get(updated["connection_id"])
    assert conn.connection_type == "snowflake"


async def test_parquet_s3_destination_aliases_fsspec_keys():
    c_store = FakeConnectionStore()
    dest = {
        "id": "d1",
        "config": {
            "type": "parquet_s3", "bucket_url": "s3://out/data.parquet",
            "storage_options": {"key": "K", "secret": "S"},
        },
    }
    updated, _ = await _migrate_destination(dest, c_store, log=[])
    conn = await c_store.get(updated["connection_id"])
    # fsspec `key/secret` rewritten to dlt-aligned aws_*.
    assert conn.credentials_dict()["aws_access_key_id"] == "K"
    assert conn.credentials_dict()["aws_secret_access_key"] == "S"
    assert "storage_options" not in updated["config"]


async def test_idempotent_when_already_has_connection_id():
    c_store = FakeConnectionStore()
    src = {
        "id": "s1", "connection_id": "already_set", "source_type": "filesystem",
        "config": {"bucket_url": "/tmp"}, "table": "t",
    }
    updated, changed = await _migrate_source(src, c_store, log=[])
    assert not changed
    assert updated == src
