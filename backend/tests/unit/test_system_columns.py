"""System columns survive user projection.

`extract` and `structure` emit columns the *product* depends on —
`artifact_ref` points at the source document, `extract_meta.key` at the cached
parse holding the word boxes, `structure_meta` at per-field provenance. None
of them is interesting to look at in a table, so the natural user action is to
add a `select` that tidies them away. Doing so silently destroys the ability
to verify the output: the columns that make a row checkable are exactly the
ones that look like noise.

So `select` keeps them. A user projection expresses which *data* columns to
carry forward, not whether the row remembers where it came from.
"""

import ibis
import pytest

from dte.compiler.ibis_compiler import SYSTEM_COLUMNS, _dispatch_single_table_step


@pytest.fixture
def extracted():
    """A table shaped like the output of extract → structure."""
    return ibis.memtable(
        [
            {
                "filename": "inv-1001.pdf",
                "page": 1,
                "invoice_no": "INV-1001",
                "total": 1240.5,
                "artifact_ref": "artifact://" + "a" * 64,
                "block_index": 0,
                "extract_meta": '{"key": "abc"}',
                "structure_meta": '{"fields": {}}',
            }
        ]
    )


def _select(table, **step):
    return _dispatch_single_table_step(table, {"op": "select", **step}, {})


def test_keep_mode_retains_system_columns(extracted):
    out = _select(extracted, fields=[{"field": "invoice_no"}]).execute()
    assert "invoice_no" in out.columns
    for c in SYSTEM_COLUMNS:
        assert c in out.columns, f"{c} was dropped by a user projection"


def test_drop_mode_retains_system_columns(extracted):
    """Drop mode is the more dangerous one: the builder derives the keep-set
    from the schema, so a user who never typed `artifact_ref` still strips it."""
    out = _select(extracted, drop=["total", "artifact_ref"]).execute()
    assert "total" not in out.columns
    for c in SYSTEM_COLUMNS:
        assert c in out.columns


def test_user_columns_keep_their_order_and_come_first(extracted):
    """System columns are plumbing — they belong after the data, or every
    table in the UI opens on a wall of hashes."""
    out = _select(
        extracted, fields=[{"field": "total"}, {"field": "invoice_no"}]
    ).execute()
    assert list(out.columns)[:2] == ["total", "invoice_no"]


def test_aliases_still_work(extracted):
    out = _select(
        extracted, fields=[{"field": "invoice_no", "alias": "number"}]
    ).execute()
    assert "number" in out.columns
    assert "artifact_ref" in out.columns


def test_explicitly_selecting_a_system_column_does_not_duplicate_it(extracted):
    out = _select(
        extracted, fields=[{"field": "invoice_no"}, {"field": "artifact_ref"}]
    ).execute()
    assert list(out.columns).count("artifact_ref") == 1


def test_a_pipeline_with_no_documents_is_unaffected():
    """No phantom columns: this must not change ordinary pipelines at all."""
    t = ibis.memtable([{"a": 1, "b": 2, "c": 3}])
    out = _dispatch_single_table_step(
        t, {"op": "select", "fields": [{"field": "a"}]}, {}
    ).execute()
    assert list(out.columns) == ["a"]


def test_the_frontend_list_matches_this_one():
    """The builder hides these from its field pickers, so the two lists are
    one contract in two languages. A name the frontend hides that the
    compiler does not protect becomes a column the user can neither see nor
    keep — invisible in the UI and silently dropped by any projection.
    """
    import re
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[3]
        / "frontend/src/lib/system-columns.ts"
    )
    if not src.exists():  # backend-only checkouts
        pytest.skip("frontend not present")

    block = re.search(
        r"SYSTEM_COLUMNS: ReadonlySet<string> = new Set\(\[(.*?)\]\)", src.read_text(), re.S
    )
    assert block, "SYSTEM_COLUMNS not found in system-columns.ts"
    assert set(re.findall(r'"([^"]+)"', block.group(1))) == set(SYSTEM_COLUMNS)


def test_aggregate_after_select_still_drops_system_columns(extracted):
    """Retention is not a promise that they survive *every* step — an
    aggregate legitimately collapses rows and the refs stop being meaningful.
    Pinned so the retention rule is not mistaken for a global invariant."""
    out = _dispatch_single_table_step(
        extracted,
        {
            "op": "aggregate",
            "group_by": ["filename"],
            "aggregations": [{"field": "total", "func": "sum", "alias": "t"}],
        },
        {},
    ).execute()
    assert "artifact_ref" not in out.columns
