"""Every DuckDB connection takes its resource limits from config (plan 086 task 2)."""
from dte.engine.connect import connect_duckdb
from dte.engine.duckdb_engine import DuckDBEngine


def _setting(con, name):
    return con.con.execute(f"SELECT current_setting('{name}')").fetchone()[0]


def test_applies_configured_limits(monkeypatch, tmp_path):
    monkeypatch.setenv("DTE_DUCKDB_MEMORY_LIMIT", "512MB")
    monkeypatch.setenv("DTE_DUCKDB_THREADS", "2")
    monkeypatch.setenv("DTE_DUCKDB_TEMP_DIR", str(tmp_path))
    con = connect_duckdb()
    assert _setting(con, "memory_limit") in ("512.0 MiB", "488.2 MiB")
    assert _setting(con, "threads") == 2
    assert _setting(con, "temp_directory") == str(tmp_path)


def test_unset_keeps_duckdb_defaults(monkeypatch):
    for k in ("DTE_DUCKDB_MEMORY_LIMIT", "DTE_DUCKDB_THREADS", "DTE_DUCKDB_TEMP_DIR"):
        monkeypatch.delenv(k, raising=False)
    assert connect_duckdb().con.execute("SELECT 1").fetchone() == (1,)


def test_engine_connection_goes_through_it(monkeypatch):
    monkeypatch.setenv("DTE_DUCKDB_THREADS", "3")
    assert _setting(DuckDBEngine().con, "threads") == 3
