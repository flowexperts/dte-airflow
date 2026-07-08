import pytest
import json
import ibis
from dte.models.pipeline import DltSource
from dte.sources.dlt_loader import load_source


def test_load_local_json_via_dlt(tmp_path):
    data = [{"name": "alice", "age": 30}, {"name": "bob", "age": 25}]
    f = tmp_path / "input.json"
    f.write_text(json.dumps(data))

    src = DltSource(
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


def test_load_returns_ibis_table(tmp_path):
    data = [{"x": 1}]
    f = tmp_path / "data.json"
    f.write_text(json.dumps(data))

    src = DltSource(
        id="s2",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": "data.json"},
        table="data",
    )
    con = ibis.duckdb.connect()
    result = load_source(src, con)
    assert isinstance(result, ibis.Table)


def test_missing_file_raises(tmp_path):
    src = DltSource(
        id="s3",
        source_type="filesystem",
        config={"bucket_url": str(tmp_path / "nonexistent"), "file_glob": "*.json"},
        table="missing",
    )
    con = ibis.duckdb.connect()
    with pytest.raises(Exception):
        load_source(src, con)


def test_unknown_source_type_raises():
    src = DltSource(
        id="s4",
        source_type="nonesuch",
        config={},
        table="t",
    )
    con = ibis.duckdb.connect()
    with pytest.raises(NotImplementedError, match="nonesuch"):
        load_source(src, con)


def test_resolve_secret_returns_literal():
    from dte.sources.dlt_loader import resolve_secret
    assert resolve_secret("literal") == "literal"


def test_resolve_secret_reads_env(monkeypatch):
    from dte.sources.dlt_loader import resolve_secret
    monkeypatch.setenv("DTE_TEST_SECRET", "shhh")
    assert resolve_secret({"env": "DTE_TEST_SECRET"}) == "shhh"


def test_resolve_secret_missing_env_raises(monkeypatch):
    from dte.sources.dlt_loader import resolve_secret
    monkeypatch.delenv("DTE_TEST_MISSING", raising=False)
    with pytest.raises(KeyError, match="DTE_TEST_MISSING"):
        resolve_secret({"env": "DTE_TEST_MISSING"})
