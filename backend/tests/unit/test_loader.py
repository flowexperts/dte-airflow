import pytest
import json
import ibis
from dte.engine.backend_registry import BackendRegistry
from dte.models.pipeline import Connection, Source, SourceCreate
from dte.sources.loader import UnsupportedFileFormat, _detect_format, load_source


def test_load_local_json_via_dlt(tmp_path):
    data = [{"name": "alice", "age": 30}, {"name": "bob", "age": 25}]
    f = tmp_path / "input.json"
    f.write_text(json.dumps(data))

    src = Source(connection_id="local_fs",
        id="s1",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "input.json"},
        table="input",
    )
    con = ibis.duckdb.connect()
    result = load_source(src, BackendRegistry(duckdb_con=con), None, {})

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

    src = Source(connection_id="local_fs",
        id="s_jsonl",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "*.jsonl"},
        table="orders",
    )
    con = ibis.duckdb.connect()
    table = load_source(src, BackendRegistry(duckdb_con=con), None, {})

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

    src = Source(connection_id="local_fs",
        id="s_csv",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "*.csv"},
        table="people",
    )
    con = ibis.duckdb.connect()
    df = load_source(src, BackendRegistry(duckdb_con=con), None, {}).execute()
    assert sorted(df["name"].tolist()) == ["alice", "bob"]


def test_load_xlsx(tmp_path):
    """Round-trip an xlsx via DuckDB's excel extension.

    Generating the fixture with DuckDB itself keeps `openpyxl` out of
    the test deps, matching how the writer produces xlsx in prod.
    """
    fixture = tmp_path / "people.xlsx"
    gen = ibis.duckdb.connect()
    gen.raw_sql("INSTALL excel")
    gen.raw_sql("LOAD excel")
    gen.raw_sql(
        f"COPY (SELECT * FROM (VALUES (1,'alice',30),(2,'bob',25)) "
        f"AS t(id,name,age)) TO '{fixture}' (FORMAT xlsx, HEADER true)"
    )

    src = Source(connection_id="local_fs",
        id="s_xlsx",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "*.xlsx"},
        table="people",
    )
    con = ibis.duckdb.connect()
    df = load_source(src, BackendRegistry(duckdb_con=con), None, {}).execute()
    assert sorted(df["name"].tolist()) == ["alice", "bob"]


def test_load_parquet(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq

    tbl = pa.table({"id": [1, 2], "name": ["alice", "bob"]})
    pq.write_table(tbl, str(tmp_path / "data.parquet"))

    src = Source(connection_id="local_fs",
        id="s_parq",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "*.parquet"},
        table="people",
    )
    con = ibis.duckdb.connect()
    df = load_source(src, BackendRegistry(duckdb_con=con), None, {}).execute()
    assert sorted(df["name"].tolist()) == ["alice", "bob"]


def test_load_jsonl_ignores_blank_lines(tmp_path):
    f = tmp_path / "orders.jsonl"
    f.write_text('{"id": "a"}\n\n{"id": "b"}\n   \n')

    src = Source(connection_id="local_fs",
        id="s_blank",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "*.jsonl"},
        table="orders",
    )
    con = ibis.duckdb.connect()
    df = load_source(src, BackendRegistry(duckdb_con=con), None, {}).execute()
    assert sorted(df["id"].tolist()) == ["a", "b"]


def test_load_explicit_format_overrides_extension(tmp_path):
    # File named .json but is really NDJSON — explicit format wins.
    f = tmp_path / "wrong-ext.json"
    f.write_text('{"id": "x"}\n{"id": "y"}\n')

    src = Source(connection_id="local_fs",
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
    df = load_source(src, BackendRegistry(duckdb_con=con), None, {}).execute()
    assert sorted(df["id"].tolist()) == ["x", "y"]


# ── format detection ────────────────────────────────────────────────────────
#
# `_detect_format` used to fall back to "json" for any unrecognised extension,
# so a `*.pdf` glob was silently routed into `read_json_auto` and died with a
# JSON parse error naming neither the file nor the real problem. Unknown
# extensions now raise, and the message has to be actionable.


@pytest.mark.parametrize(
    "ext",
    [".json", ".jsonl", ".ndjson", ".csv", ".tsv", ".parquet", ".pq", ".xlsx"],
)
def test_detect_format_known_extensions(ext):
    """Every supported extension still resolves to a reader family."""
    assert _detect_format(f"data{ext}", None) in {
        "json", "jsonl", "csv", "parquet", "excel",
    }


@pytest.mark.parametrize(
    "path",
    ["report.pdf", "scan.PDF", "clip.mp3", "notes.txt", "archive.tar.gz"],
)
def test_detect_format_unknown_extension_raises(path):
    with pytest.raises(UnsupportedFileFormat) as exc:
        _detect_format(path, None)
    msg = str(exc.value)
    assert path in msg          # name the offending path
    assert "format" in msg      # point at the override


def test_detect_format_extensionless_raises():
    """`**/*` has no extension to detect — guessing json is how the old bug
    surfaced as an unrelated parse error deep inside DuckDB."""
    with pytest.raises(UnsupportedFileFormat):
        _detect_format("**/*", None)


def test_detect_format_explicit_still_wins_over_unknown_extension():
    """The 'wrong extension, right content' escape hatch must survive the fix."""
    assert _detect_format("data.pdf", "csv") == "csv"
    assert _detect_format("**/*", "jsonl") == "jsonl"
    assert _detect_format("data.weird", "ndjson") == "jsonl"


def test_load_pdf_glob_raises_actionable_error(tmp_path):
    """End to end: a documents-shaped glob fails at detection, not with a
    JSON parse error from inside read_json_auto."""
    (tmp_path / "invoice.pdf").write_bytes(b"%PDF-1.4 not really a pdf")

    src = Source(
        connection_id="local_fs",
        id="s_pdf",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "*.pdf"},
        table="docs",
    )
    con = ibis.duckdb.connect()
    with pytest.raises(UnsupportedFileFormat) as exc:
        load_source(src, BackendRegistry(duckdb_con=con), None, {})
    assert ".pdf" in str(exc.value)


def test_load_returns_ibis_table(tmp_path):
    data = [{"x": 1}]
    f = tmp_path / "data.json"
    f.write_text(json.dumps(data))

    src = Source(connection_id="local_fs",
        id="s2",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "data.json"},
        table="data",
    )
    con = ibis.duckdb.connect()
    result = load_source(src, BackendRegistry(duckdb_con=con), None, {})
    assert isinstance(result, ibis.Table)


def test_missing_file_raises(tmp_path):
    src = Source(connection_id="local_fs",
        id="s3",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path / "nonexistent"), "file_glob": "*.json"},
        table="missing",
    )
    con = ibis.duckdb.connect()
    with pytest.raises(Exception):
        load_source(src, BackendRegistry(duckdb_con=con), None, {})


def test_unknown_source_type_rejected_at_model():
    """SourceCreate.source_type is a Literal — bogus values fail validation
    before ever reaching the loader. Source(table=True) accepts str for ORM
    compatibility; SourceCreate is the API-edge class that enforces the Literal.
    """
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SourceCreate(
            connection_id="local_fs",
            id="s4",
            source_type="nonesuch",
            config={},
            table="t",
        )


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


def test_dispatch_registers_object_storage_types():
    from dte.sources.loader import LOADERS
    assert "s3" in LOADERS
    assert "gcs" in LOADERS
    assert "azure" in LOADERS


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

    src = Source(connection_id="local_fs",
        id="sql1",
        source_type="sql_database",
        config={},
        table="customers_out",
    )
    con = ibis.duckdb.connect()
    result = load_source(src, BackendRegistry(duckdb_con=con), Connection(id="c", connection_type="sqlite"), {"url": f"sqlite:///{db_path}"}, table="customers")
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
    src = Source(connection_id="local_fs",
        id="sql2",
        source_type="sql_database",
        config={},
        table="t_out",
    )
    con = ibis.duckdb.connect()
    # Credentials come from the connection; env-indirection still supported on
    # individual values for the env-backed SecretResolver.
    result = load_source(src, BackendRegistry(duckdb_con=con), Connection(id="c", connection_type="sqlite"), {"url": {"env": "DTE_SQL_DSN"}}, table="t")
    df = result.execute()
    assert df["x"].tolist() == [42]


def test_dispatch_registers_sql_database():
    from dte.sources.loader import LOADERS
    assert "sql_database" in LOADERS


def test_sql_database_snowflake_without_extra_raises_helpfully():
    """Snowflake is a supported connection type in the new architecture, but
    routing to it requires the `snowflake-source` extra. Without it, the
    loader should raise a clear error pointing at the missing extra."""
    src = Source(connection_id="local_fs",
        id="sql_snow",
        source_type="sql_database",
        config={},
        table="t",
    )
    con = ibis.duckdb.connect()
    # Extra not installed in the dev env → RuntimeError mentioning the extra.
    with pytest.raises(RuntimeError, match="snowflake-source"):
        load_source(src, BackendRegistry(duckdb_con=con), Connection(id="c", connection_type="snowflake"), {"url": "snowflake://user:pw@acct"}, table="t")


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

    src = Source(connection_id="local_fs",
        id="mongo1",
        source_type="mongodb",
        config={"database": "mydb", "collection": "mycoll"},
        table="mongo_out",
    )
    con = ibis.duckdb.connect()
    result = load_source(src, BackendRegistry(duckdb_con=con), None, {"url": "mongodb://ignored"})
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

    src = Source(connection_id="local_fs",
        id="mongo2",
        source_type="mongodb",
        config={"database": "d", "collection": "c"},
        table="m2",
    )
    con = ibis.duckdb.connect()
    load_source(src, BackendRegistry(duckdb_con=con), None, {"url": {"env": "DTE_MONGO_URL"}})
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

        src = Source(connection_id="local_fs",
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
        result = load_source(src, BackendRegistry(duckdb_con=con), None, {})
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
        src = Source(connection_id="local_fs",
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
        result = load_source(src, BackendRegistry(duckdb_con=con), None, {})
        df = result.execute()
    assert len(df) == 1
    assert df["x"].tolist() == [1]


def test_dispatch_registers_rest_api():
    from dte.sources.loader import LOADERS
    assert "rest_api" in LOADERS


# ── Whitespace in path-ish config ────────────────────────────────────────
#
# A trailing space survives copy-paste and is invisible in the input box. It
# used to turn a correct glob into "No files matched '**/*.pdf '", an error
# that reads as if the pattern were wrong. Trimmed at save, and again at glob
# time so sources stored before the fix keep working.


def test_glob_local_tolerates_surrounding_whitespace(tmp_path):
    from dte.sources.loader import _glob_local

    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4")

    clean = _glob_local(str(tmp_path), "**/*.pdf")
    assert len(clean) == 2

    assert _glob_local(str(tmp_path), "**/*.pdf ") == clean
    assert _glob_local(str(tmp_path), " **/*.pdf") == clean
    assert _glob_local(str(tmp_path) + " ", "**/*.pdf") == clean


def test_source_save_trims_bucket_url_and_file_glob():
    src = SourceCreate(
        id="docs",
        name="docs",
        connection_id="local_fs",
        source_type="documents",
        table="docs",
        config={"bucket_url": "  /tmp/docs  ", "file_glob": "**/*.pdf "},
    )
    assert src.config["bucket_url"] == "/tmp/docs"
    assert src.config["file_glob"] == "**/*.pdf"


def test_source_save_leaves_clean_config_untouched():
    src = SourceCreate(
        id="docs",
        name="docs",
        connection_id="local_fs",
        source_type="documents",
        table="docs",
        config={"bucket_url": "/tmp/docs", "file_glob": "**/*.pdf"},
    )
    assert src.config["bucket_url"] == "/tmp/docs"
    assert src.config["file_glob"] == "**/*.pdf"


# ── Blank id means "server, name it" ─────────────────────────────────────
#
# `default_factory` only fires when the key is absent, so a client sending
# {"id": ""} used to write an empty string as the primary key. The row saved,
# then a pipeline slot holding "" failed validation claiming nothing was
# picked — an error pointing away from the actual cause.


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_source_id_is_server_generated(blank):
    src = SourceCreate(
        id=blank,
        name="PDF source",
        connection_id="local_fs",
        source_type="documents",
        table="docs",
        config={"bucket_url": "/tmp/docs", "file_glob": "**/*.pdf"},
    )
    assert len(src.id) == 36, f"expected a uuid4, got {src.id!r}"


def test_explicit_source_id_is_preserved():
    src = SourceCreate(
        id="my-invoices",
        name="PDF source",
        connection_id="local_fs",
        source_type="documents",
        table="docs",
        config={"bucket_url": "/tmp/docs", "file_glob": "**/*.pdf"},
    )
    assert src.id == "my-invoices"


def test_blank_id_generated_for_every_model_with_the_pattern():
    """Connection, Destination and LookupTable share the default_factory
    idiom, so they shared the bug."""
    from dte.models.pipeline import (
        Connection,
        DestinationBase,
        LookupTableBase,
    )

    conn = Connection(id="", name="c", connection_type="local_fs", credentials={})
    dest = DestinationBase(
        id="", name="d", connection_id="local_fs",
        config={"type": "json_file", "path": "/tmp/o.json"},
    )
    lut = LookupTableBase(id="", name="l", mappings={"a": "b"})
    for obj in (conn, dest, lut):
        assert len(obj.id) == 36, f"{type(obj).__name__} kept a blank id"


def test_object_store_source_reads_through_the_connections_filesystem(monkeypatch):
    """s3/gcs/azure/sftp sources read via the Airflow provider's filesystem (plan 074)."""
    import json

    import fsspec

    from dte.engine.backend_registry import BackendRegistry
    from dte.models.pipeline import Connection, Source
    from dte.sources import object_store
    from dte.sources.loader import load_source

    fs = fsspec.filesystem("memory", skip_instance_cache=True)
    fs.store.clear()
    fs.pipe("/b/orders/2026/a.json", json.dumps([{"id": 1, "amount": 5}, {"id": 2, "amount": 50}]).encode())
    seen = []
    monkeypatch.setattr(object_store, "_provider_fs", lambda url, conn_id: seen.append(conn_id) or fs)

    conn = Connection.model_construct(id="aws_prod", connection_type="s3",
                                      credentials={"conn_id": "aws_prod"})
    src = Source(id="o", source_type="s3", table="orders",
                 config={"bucket_url": "s3://b/orders", "file_glob": "**/*.json"})
    t = load_source(src, BackendRegistry(), conn, conn.credentials)
    assert sorted(t.execute()["id"]) == [1, 2]
    assert seen == ["aws_prod"]

