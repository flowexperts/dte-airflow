"""Output targets are format-only and location-agnostic.

Before this, each target class pinned a format to one location
(`json_file` → local disk, `parquet_s3` → S3). Format and location are now
independent axes: any of json/csv/parquet/excel writes to local_fs, s3, gcs
or azure.

Legacy `*_file` / `parquet_s3` discriminator values must keep parsing —
they're persisted in the `destinations` table.
"""

import ibis
import pandas as pd
import pytest
from pydantic import TypeAdapter, ValidationError

from dte.models.pipeline import (
    DESTINATION_CONNECTION_COMPAT,
    ENGINE_WRITE_SUPPORT,
    CsvTarget,
    Destination,
    DestinationBase,
    ExcelTarget,
    JsonTarget,
    OutputTarget,
    ParquetTarget,
)
from dte.sources.duckdb_secrets import backend_for_uri

_adapter = TypeAdapter(OutputTarget)


@pytest.fixture
def sample_table():
    con = ibis.duckdb.connect()
    df = pd.DataFrame([
        {"id": 1, "name": "alice", "score": 90.5},
        {"id": 2, "name": "bob", "score": 42.0},
    ])
    con.create_table("t", df, overwrite=True)
    return con.table("t")


# ─── discriminators ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("type_name,cls", [
    ("json", JsonTarget), ("csv", CsvTarget),
    ("excel", ExcelTarget), ("parquet", ParquetTarget),
])
def test_format_only_type_names(type_name, cls):
    ext = {"json": ".json", "csv": ".csv", "excel": ".xlsx", "parquet": ".parquet"}[type_name]
    target = _adapter.validate_python({"type": type_name, "path": f"/tmp/out{ext}"})
    assert isinstance(target, cls)
    assert target.type == type_name


@pytest.mark.parametrize("legacy,expected", [
    ("json_file", "json"), ("csv_file", "csv"),
    ("excel_file", "excel"), ("parquet_s3", "parquet"),
])
def test_legacy_type_names_still_parse(legacy, expected):
    """Persisted rows predate the rename — they must not 422 on read."""
    ext = {"json": ".json", "csv": ".csv", "excel": ".xlsx", "parquet": ".parquet"}[expected]
    dest = DestinationBase(
        id="d1", connection_id="c1", config={"type": legacy, "path": f"/tmp/out{ext}"},
    )
    assert dest.config.type == expected


def test_legacy_parquet_bucket_url_alias():
    """`parquet_s3` used `bucket_url`, not `path`."""
    dest = DestinationBase(
        id="d1", connection_id="c1",
        config={"type": "parquet_s3", "bucket_url": "s3://b/out.parquet"},
    )
    assert dest.config.type == "parquet"
    assert dest.config.path == "s3://b/out.parquet"


def test_narrow_config_coerces_legacy_on_orm_hydration():
    """`table=True` skips validators, so the store calls narrow_config()."""
    dest = Destination(id="d1", connection_id="c1", config={})
    # Mimic SQLAlchemy handing back a raw JSONB dict written before the rename.
    object.__setattr__(dest, "config", {"type": "json_file", "path": "/tmp/out.json"})
    assert dest.narrow_config().config.type == "json"


# ─── extension validation survives the rename ────────────────────────────────

def test_extension_family_mismatch_still_rejected():
    with pytest.raises(ValidationError):
        _adapter.validate_python({"type": "json", "path": "/tmp/out.csv"})


def test_missing_extension_still_rejected():
    with pytest.raises(ValidationError):
        _adapter.validate_python({"type": "parquet", "path": "s3://bucket/out"})


@pytest.mark.parametrize("path", [".jsonl", ".ndjson"])
def test_json_family_extensions_accepted(path):
    assert _adapter.validate_python({"type": "json", "path": f"/tmp/o{path}"}).type == "json"


# ─── every format reaches every object store ─────────────────────────────────

@pytest.mark.parametrize("type_name,ext", [
    ("json", ".json"), ("csv", ".csv"), ("excel", ".xlsx"), ("parquet", ".parquet"),
])
@pytest.mark.parametrize("scheme", ["s3://b", "gcs://b", "az://b", "/local"])
def test_any_format_any_location_validates(type_name, ext, scheme):
    target = _adapter.validate_python({"type": type_name, "path": f"{scheme}/out{ext}"})
    assert target.type == type_name


@pytest.mark.parametrize("type_name", ["json", "csv", "excel", "parquet"])
def test_compat_map_allows_all_object_stores(type_name):
    assert DESTINATION_CONNECTION_COMPAT[type_name] >= {"local_fs", "s3", "gcs", "azure"}


@pytest.mark.parametrize("engine", [
    "duckdb", "postgres", "mysql", "sqlite", "bigquery", "snowflake", "trino",
])
def test_every_engine_can_write_files_anywhere(engine):
    """This is the gate that actually fires (validate_pipeline_engine_compat).

    Non-DuckDB engines stage through a scratch DuckDB connection, so they
    are not limited to their own database + local disk.
    """
    assert ENGINE_WRITE_SUPPORT[engine] >= {"local_fs", "s3", "gcs", "azure"}


def test_write_from_non_duckdb_backend(tmp_path):
    """A result living in another engine still reaches a file target."""
    from dte.engine.writers import write

    sqlite_con = ibis.sqlite.connect()
    sqlite_con.create_table(
        "t", pd.DataFrame([{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}])
    )
    table = sqlite_con.table("t")
    assert not type(table._find_backend()).__module__.startswith("ibis.backends.duckdb")

    out = tmp_path / "out.json"
    result = write(table, _adapter.validate_python({"type": "json", "path": str(out)}))
    assert result["rows_written"] == 2
    assert out.exists()


# ─── URI → storage backend routing ───────────────────────────────────────────

@pytest.mark.parametrize("uri,expected", [
    ("s3://b/k.parquet", "s3"),
    ("gcs://b/k.parquet", "gcs"),
    ("gs://b/k.parquet", "gcs"),
    ("az://b/k.parquet", "azure"),
    ("azure://b/k.parquet", "azure"),
    ("S3://b/k.parquet", "s3"),
    ("/tmp/out.parquet", None),
    ("file:///tmp/out.parquet", None),
    ("relative/out.parquet", None),
])
def test_backend_for_uri(uri, expected):
    assert backend_for_uri(uri) == expected


def test_abfss_not_routed():
    """DuckDB's azure extension rejects abfss:// under connection-string auth
    (the form Azurite needs), so it must not be advertised as supported."""
    assert backend_for_uri("abfss://container/k.parquet") is None


# ─── writers round-trip locally for every format ─────────────────────────────

@pytest.mark.parametrize("type_name,ext,reader", [
    ("json", ".json", "read_json_auto"),
    ("csv", ".csv", "read_csv_auto"),
    ("parquet", ".parquet", "read_parquet"),
    ("excel", ".xlsx", "read_xlsx"),
])
def test_local_write_roundtrip(tmp_path, sample_table, type_name, ext, reader):
    from dte.engine.writers import write

    out = tmp_path / f"out{ext}"
    target = _adapter.validate_python({"type": type_name, "path": str(out)})
    result = write(sample_table, target)

    assert result["rows_written"] == 2
    assert result["location"] == str(out)
    assert out.exists()

    con = ibis.duckdb.connect()
    if type_name == "excel":
        con.raw_sql("INSTALL excel")
        con.raw_sql("LOAD excel")
    (n,) = con.con.execute(f"SELECT COUNT(*) FROM {reader}('{out}')").fetchone()
    assert n == 2


def test_extension_install_survives_missing_home(monkeypatch, tmp_path, sample_table):
    """Container images often run as a user whose $HOME was never created.

    DuckDB caches extensions under $HOME, so `INSTALL` would fail with
    "Can't find the home directory", taking out every s3/gcs/azure read and
    write. Excel needs a real INSTALL, so it exercises the path.
    """
    import dte.sources.duckdb_secrets as ds

    monkeypatch.setenv("HOME", "/nonexistent/home/dte")
    monkeypatch.delenv("DTE_DUCKDB_HOME", raising=False)
    monkeypatch.setattr(ds, "_INSTALLED_EXTS", set())  # force a real INSTALL

    from dte.engine.writers import write

    out = tmp_path / "out.xlsx"
    result = write(sample_table, _adapter.validate_python({"type": "excel", "path": str(out)}))
    assert result["rows_written"] == 2
    assert out.exists()


def test_unknown_scheme_is_rejected(sample_table):
    """A typo'd scheme must not silently create a local file named 'ftp:/...'."""
    from dte.engine.writers import write

    target = _adapter.validate_python({"type": "json", "path": "ftp://host/out.json"})
    with pytest.raises(ValueError, match="unsupported scheme"):
        write(sample_table, target)
