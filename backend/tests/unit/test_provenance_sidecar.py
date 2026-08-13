"""The deliverable is the user's; provenance is ours.

System columns must not reach the destination — a customer's CSV should not
carry our content hashes — but the run-output surface still has to inspect
what actually ran. So they are split at the writer boundary: user columns to
the destination, system columns to the artifact store.

The sharp edge is alignment. The output file has no row identity, so the
sidecar can only be rejoined by position, and that is only sound because both
sides read from one materialisation ordered by an explicit row number.
"""

import json

import ibis
import pytest

from dte.artifacts import get_artifact_store, run_provenance_key
from dte.engine.writers.provenance import (
    read_provenance,
    split_off_provenance,
    system_columns_in,
)


@pytest.fixture
def con():
    return ibis.duckdb.connect()


def _rows(n: int) -> list[dict]:
    return [
        {
            "invoice_no": f"INV-{1000 + i}",
            "total": float(i),
            "artifact_ref": f"artifact://{i:064x}",
            "extract_meta": json.dumps({"key": f"k{i}"}),
            "structure_meta": json.dumps({"fields": {"total": {"quote": str(i)}}}),
            "block_index": i,
        }
        for i in range(n)
    ]


def _table(con, n):
    return con.create_table("t", ibis.memtable(_rows(n)), overwrite=True)


def test_deliverable_loses_the_system_columns(con, tmp_path, monkeypatch):
    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path))
    out, key = split_off_provenance(_table(con, 3), "run-1", con=con)
    assert set(out.columns) == {"invoice_no", "total"}
    assert key == run_provenance_key("run-1")


def test_sidecar_rows_line_up_with_the_deliverable_rows(con, tmp_path, monkeypatch):
    """The assertion the whole design rests on.

    A mismatch here attributes one document's provenance to another row —
    the inspector would confidently highlight the wrong invoice, which is
    worse than showing nothing at all.
    """
    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path))
    out, _ = split_off_provenance(_table(con, 200), "run-2", con=con)

    delivered = out.execute()
    captured = read_provenance("run-2")
    assert len(captured) == len(delivered) == 200

    for i, (_, row) in enumerate(delivered.iterrows()):
        # `INV-1007` must sit beside the provenance whose block_index is 7.
        expected = int(row["invoice_no"].removeprefix("INV-")) - 1000
        assert captured[i]["block_index"] == expected, f"row {i} misaligned"


def test_ordinary_pipelines_are_untouched_and_write_nothing(con, tmp_path, monkeypatch):
    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path))
    plain = con.create_table("p", ibis.memtable([{"a": 1, "b": 2}]), overwrite=True)
    out, key = split_off_provenance(plain, "run-3", con=con)

    assert key is None
    assert list(out.columns) == ["a", "b"]
    assert not get_artifact_store().exists(run_provenance_key("run-3"))


def test_row_count_is_preserved(con, tmp_path, monkeypatch):
    """Materialising through a temp table must not drop or duplicate rows —
    `rows_written` is reported from the delivered table."""
    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path))
    out, _ = split_off_provenance(_table(con, 57), "run-4", con=con)
    assert out.count().execute() == 57


def test_capped_so_a_huge_export_cannot_become_the_biggest_object(
    con, tmp_path, monkeypatch
):
    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setattr("dte.engine.writers.provenance.MAX_PROVENANCE_ROWS", 10)
    out, _ = split_off_provenance(_table(con, 40), "run-5", con=con)

    # Every row is still delivered — only provenance is bounded.
    assert out.count().execute() == 40
    assert len(read_provenance("run-5")) == 10


def test_reading_provenance_for_an_unknown_run_is_empty_not_an_error(
    tmp_path, monkeypatch
):
    """Runs that predate this, or whose sidecar was evicted, must degrade to
    "no Inspect" rather than failing the output endpoint."""
    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path))
    assert read_provenance("never-ran") == []


def test_corrupt_sidecar_degrades_instead_of_raising(tmp_path, monkeypatch):
    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path))
    get_artifact_store().put(
        run_provenance_key("run-6"), b"{not json", "application/json"
    )
    assert read_provenance("run-6") == []


def test_system_columns_in_preserves_table_order(con):
    t = con.create_table("o", ibis.memtable(_rows(1)), overwrite=True)
    assert system_columns_in(t) == [
        c for c in t.columns if c in system_columns_in(t)
    ]
