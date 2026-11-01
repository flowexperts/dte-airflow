"""A COPY that fails halfway leaves no truncated file behind (plan 086 task 4).

DuckDB already guarantees this locally: an existing target is written via a
temp file and renamed (`USE_TMP_FILE`), and a fresh target is removed on
error. This pins that behaviour so a DuckDB upgrade can't silently drop it.
"""
import ibis
import pytest

from dte.engine.writers._copy import copy_to

FORMATS = ["FORMAT CSV, HEADER", "FORMAT PARQUET", "FORMAT JSON, ARRAY true"]


def _failing_table():
    # Fails well past the first row group, so some bytes are already written.
    return ibis.duckdb.connect().sql(
        "SELECT CASE WHEN i < 100000 THEN i::VARCHAR ELSE error('boom') END AS v "
        "FROM range(200000) r(i)"
    )


@pytest.mark.parametrize("fmt", FORMATS)
def test_failed_copy_keeps_old_contents(tmp_path, fmt):
    out = tmp_path / "out"
    out.write_text("previous")
    with pytest.raises(Exception, match="boom"):
        copy_to(_failing_table(), str(out), fmt)
    assert out.read_text() == "previous"
    assert [p.name for p in tmp_path.iterdir()] == ["out"]


@pytest.mark.parametrize("fmt", FORMATS)
def test_failed_copy_to_fresh_path_leaves_nothing(tmp_path, fmt):
    out = tmp_path / "out"
    with pytest.raises(Exception, match="boom"):
        copy_to(_failing_table(), str(out), fmt)
    assert list(tmp_path.iterdir()) == []
