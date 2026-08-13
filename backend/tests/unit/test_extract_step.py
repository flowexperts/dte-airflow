"""The `extract` step and the enrichment engine seam.

This is the architecturally risky part of plan 050: every other step is a lazy
ibis expression, and enrichment cannot be. A model call is per-row, slow,
rate-limited and billable — it must not sit inside a DuckDB scan where it gets
re-evaluated on every downstream reference.

So enrichment *materialises*: SQL out, map in Python, register the result
back. These tests pin the consequences of that choice — fan-out, column
preservation, caching, and per-row failure isolation.
"""

import json

import ibis
import pytest

from dte.compiler.ibis_compiler import compile_pipeline
from dte.engine.base import EnrichmentSpec
from dte.engine.duckdb_engine import DuckDBEngine
from dte.models.pipeline import ExtractStep, Pipeline
from dte.sources.loader import load_source
from tests.fixtures.pdf_builder import build_pdf

PAGES = ["Invoice total 1240.50", "Vendor Acme Industrial", "Issued 2024-03-01"]


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    docs = tmp_path / "docs"
    docs.mkdir()
    # Distinct content per file, so cache assertions are unambiguous —
    # byte-identical documents legitimately share one cache entry, which is
    # what test_identical_documents_share_one_cache_entry covers separately.
    (docs / "a.pdf").write_bytes(build_pdf(PAGES))
    (docs / "b.pdf").write_bytes(build_pdf([p + " (copy b)" for p in PAGES]))
    return docs


def _documents_table(corpus, engine):
    from dte.models.pipeline import Source

    src = Source(
        id="docs", connection_id="local_fs", source_type="documents",
        config={"bucket_url": str(corpus), "file_glob": "*.pdf"}, table="docs",
    )
    from dte.engine.backend_registry import BackendRegistry

    return load_source(src, BackendRegistry(duckdb_con=engine.con), None, {})


def _extract(engine, table, **overrides):
    from dte.compiler.ibis_compiler import _apply_extract

    step = {"op": "extract", "provider": "pdfplumber", **overrides}
    return _apply_extract(table, ExtractStep(**step), engine=engine, idx=0)


# ── the engine seam ─────────────────────────────────────────────────────────


def test_apply_enrichment_maps_rows_and_returns_an_ibis_table():
    engine = DuckDBEngine()
    t = ibis.memtable([{"n": 1}, {"n": 2}])
    spec = EnrichmentSpec(
        name="double",
        mapper=lambda row: [{"doubled": row["n"] * 2}],
        output_schema={"doubled": "BIGINT"},
    )
    out = engine.apply_enrichment(t, spec)
    assert isinstance(out, ibis.Table)
    df = out.execute().sort_values("n")
    assert df["doubled"].tolist() == [2, 4]


def test_apply_enrichment_preserves_input_columns():
    engine = DuckDBEngine()
    t = ibis.memtable([{"n": 1, "keep": "yes"}])
    spec = EnrichmentSpec(
        name="x", mapper=lambda row: [{"extra": "v"}],
        output_schema={"extra": "VARCHAR"},
    )
    df = engine.apply_enrichment(t, spec).execute()
    assert set(df.columns) >= {"n", "keep", "extra"}
    assert df.iloc[0]["keep"] == "yes"


def test_apply_enrichment_fans_out():
    """One input row may become many — the property `extract` depends on."""
    engine = DuckDBEngine()
    t = ibis.memtable([{"n": 1}, {"n": 2}])
    spec = EnrichmentSpec(
        name="fan",
        mapper=lambda row: [{"part": i} for i in range(3)],
        output_schema={"part": "BIGINT"},
    )
    assert len(engine.apply_enrichment(t, spec).execute()) == 6


def test_apply_enrichment_can_drop_rows():
    engine = DuckDBEngine()
    t = ibis.memtable([{"n": 1}, {"n": 2}])
    spec = EnrichmentSpec(
        name="drop",
        mapper=lambda row: [] if row["n"] == 1 else [{"kept": True}],
        output_schema={"kept": "BOOLEAN"},
    )
    df = engine.apply_enrichment(t, spec).execute()
    assert df["n"].tolist() == [2]


def test_apply_enrichment_on_empty_input_yields_empty_typed_table():
    engine = DuckDBEngine()
    t = ibis.memtable([{"n": 1}]).filter(ibis._.n > 99)
    spec = EnrichmentSpec(
        name="empty", mapper=lambda row: [{"v": 1}], output_schema={"v": "BIGINT"}
    )
    out = engine.apply_enrichment(t, spec)
    assert len(out.execute()) == 0
    assert "v" in out.columns


def test_enrichment_is_not_supported_on_trino():
    """Pushdown backends can't run a Python mapper. Same shape as the
    existing raw-SQL refusal."""
    from dte.engine.trino_engine import EnrichmentNotSupportedOnBackend, TrinoEngine

    engine = TrinoEngine.__new__(TrinoEngine)
    spec = EnrichmentSpec(name="x", mapper=lambda r: [], output_schema={})
    with pytest.raises(EnrichmentNotSupportedOnBackend):
        engine.apply_enrichment(ibis.memtable([{"n": 1}]), spec)


# ── extract: shape ──────────────────────────────────────────────────────────


def test_extract_fans_out_to_one_row_per_page(corpus):
    engine = DuckDBEngine()
    out = _extract(engine, _documents_table(corpus, engine)).execute()
    assert len(out) == 6                      # 2 documents × 3 pages


def test_extract_emits_content_and_provenance(corpus):
    engine = DuckDBEngine()
    out = _extract(engine, _documents_table(corpus, engine)).execute()
    assert set(out.columns) >= {
        "content", "block_index", "page", "artifact_ref", "extract_meta",
    }
    first = out.sort_values(["filename", "block_index"]).iloc[0]
    assert first["content"].strip() == PAGES[0]
    assert first["page"] == 1


def test_extract_preserves_the_listing_columns(corpus):
    engine = DuckDBEngine()
    out = _extract(engine, _documents_table(corpus, engine)).execute()
    assert set(out.columns) >= {"path", "filename", "size_bytes", "media_type"}


def test_document_granularity_yields_one_row_per_file(corpus):
    engine = DuckDBEngine()
    out = _extract(
        engine, _documents_table(corpus, engine), granularity="document"
    ).execute()
    assert len(out) == 2


def test_custom_output_field(corpus):
    engine = DuckDBEngine()
    out = _extract(
        engine, _documents_table(corpus, engine), output_field="body"
    ).execute()
    assert "body" in out.columns


def test_result_is_ordinary_tabular_data(corpus):
    """The point of the two-op split: after extract, every existing step works."""
    engine = DuckDBEngine()
    table = _extract(engine, _documents_table(corpus, engine))
    filtered = table.filter(table.page == 1).execute()
    assert len(filtered) == 2


# ── extract: caching ────────────────────────────────────────────────────────


def test_second_extract_is_served_from_cache(corpus):
    """The single most important assertion in plan 050: re-running must be
    free, or experimentation is unaffordable."""
    engine = DuckDBEngine()
    first = _extract(engine, _documents_table(corpus, engine)).execute()
    assert not first["extract_meta"].iloc[0]["cached"]

    engine2 = DuckDBEngine()
    second = _extract(engine2, _documents_table(corpus, engine2)).execute()
    assert all(m["cached"] for m in second["extract_meta"])
    assert second["content"].tolist() == first["content"].tolist()


def test_changing_provider_busts_the_cache(corpus):
    engine = DuckDBEngine()
    _extract(engine, _documents_table(corpus, engine))
    e2 = DuckDBEngine()
    out = _extract(e2, _documents_table(corpus, e2), provider="pypdf").execute()
    assert not any(m["cached"] for m in out["extract_meta"])


def test_changing_granularity_busts_the_cache(corpus):
    engine = DuckDBEngine()
    _extract(engine, _documents_table(corpus, engine))
    e2 = DuckDBEngine()
    out = _extract(e2, _documents_table(corpus, e2), granularity="document").execute()
    assert not any(m["cached"] for m in out["extract_meta"])


def test_identical_documents_share_one_cache_entry(tmp_path, monkeypatch):
    """Content-addressed: the same bytes under two names is one extraction."""
    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path / "art"))
    docs = tmp_path / "d"
    docs.mkdir()
    pdf = build_pdf(PAGES)
    (docs / "one.pdf").write_bytes(pdf)
    (docs / "two.pdf").write_bytes(pdf)

    engine = DuckDBEngine()
    out = _extract(engine, _documents_table(docs, engine)).execute()
    cached = [m["cached"] for m in out["extract_meta"]]
    assert cached.count(False) == 3 and cached.count(True) == 3


# ── extract: the document itself is an artifact ─────────────────────────────


def test_extract_stores_the_original_document_under_its_doc_key(corpus):
    """`artifact_ref` points at the *document*, not the extraction.

    Every row carries `artifact://<sha256 of the PDF bytes>`, which is what
    the document inspector dereferences to render the page. Storing only the
    derived extract JSON leaves that ref dangling — the row promises bytes
    that were never written.
    """
    from dte.artifacts import doc_key, get_artifact_store

    engine = DuckDBEngine()
    out = _extract(engine, _documents_table(corpus, engine)).execute()
    store = get_artifact_store()

    original = (corpus / "a.pdf").read_bytes()
    key = doc_key(original)
    assert key in {r.removeprefix("artifact://") for r in out["artifact_ref"]}

    assert store.exists(key), "artifact_ref points at bytes that were never stored"
    assert store.get(key) == original
    assert store.media_type(key) == "application/pdf"


def test_document_bytes_survive_a_cached_re_extract(corpus):
    """The store write sits before the cache branch, not inside the miss path.

    Otherwise a cache built by an older version — or by a run whose artifacts
    were partly evicted — can never heal: every subsequent run short-circuits
    on the derived key and the document is never written.
    """
    from dte.artifacts import doc_key, get_artifact_store

    engine = DuckDBEngine()
    _extract(engine, _documents_table(corpus, engine)).execute()

    store = get_artifact_store()
    key = doc_key((corpus / "a.pdf").read_bytes())
    # Simulate the pre-13a cache: extraction cached, document absent.
    store.delete(key)
    assert not store.exists(key)

    engine2 = DuckDBEngine()
    out = _extract(engine2, _documents_table(corpus, engine2)).execute()
    assert all(m["cached"] for m in out["extract_meta"]), "expected a cache hit"
    assert store.exists(key), "cached path skipped the document write"


def test_unreadable_document_has_no_artifact_ref(corpus):
    """A row with no bytes must not claim an artifact — a ref that 404s is
    worse than a null, because the inspector renders an error instead of
    correctly showing nothing."""
    engine = DuckDBEngine()
    table = _documents_table(corpus, engine)
    (corpus / "a.pdf").unlink()
    out = _extract(engine, table).execute()
    assert out[out["filename"] == "a.pdf"].iloc[0]["artifact_ref"] is None


def test_cached_blocks_keep_the_word_boxes(corpus):
    """Provenance highlighting resolves a char span to a rectangle via
    per-word boxes. `pdfplumber` computes them; if the cache write drops them
    the inspector can never draw a box — and because every later run is a
    cache hit, re-extracting would not bring them back either.
    """
    from dte.artifacts import get_artifact_store

    engine = DuckDBEngine()
    out = _extract(engine, _documents_table(corpus, engine)).execute()
    store = get_artifact_store()

    key = out["extract_meta"].iloc[0]["key"]
    blocks = json.loads(store.get(key).decode("utf-8"))["blocks"]
    assert blocks[0]["words"], "word boxes dropped on the way into the cache"
    assert {"x0", "x1", "top", "bottom", "text"} <= set(blocks[0]["words"][0])


def test_multi_line_pages_produce_separate_words(tmp_path, monkeypatch):
    """A newline in the source text must become a real line break.

    Emitting the whole page in one PDF text-showing operator makes pdfplumber
    decode the newline as a literal `(cid:10)` *inside* a word, so
    `extract_words()` returns run-together tokens like
    `Freight(cid:10)Invoice`. Provenance highlighting then correctly refuses
    to box anything — the quote never aligns to a word boundary — and the
    inspector looks broken on every field.
    """
    from dte.artifacts import get_artifact_store

    monkeypatch.setenv("DTE_ARTIFACT_DIR", str(tmp_path / "art"))
    docs = tmp_path / "d"
    docs.mkdir()
    (docs / "a.pdf").write_bytes(build_pdf(["ACME Freight\nInvoice INV-1001\n"]))

    engine = DuckDBEngine()
    out = _extract(engine, _documents_table(docs, engine)).execute()

    words = json.loads(
        get_artifact_store().get(out["extract_meta"].iloc[0]["key"]).decode("utf-8")
    )["blocks"][0]["words"]
    texts = [w["text"] for w in words]

    assert not any("cid:" in t for t in texts), texts
    assert "Invoice" in texts and "INV-1001" in texts, texts
    # Lines must actually differ vertically, or every word claims one row and
    # a multi-line highlight collapses into a single wrong box.
    assert len({round(w["top"]) for w in words}) == 2, words


def test_blocks_carry_page_dimensions(corpus):
    """Word boxes are in PDF points; a highlight has to be drawn in pixels.

    Without the page's own width and height there is no scale factor, and
    `bbox` is the bounds of the *content*, not the page — deriving a scale
    from it silently stretches every box on any page with a margin.
    """
    from dte.artifacts import get_artifact_store

    engine = DuckDBEngine()
    out = _extract(engine, _documents_table(corpus, engine)).execute()
    store = get_artifact_store()

    key = out["extract_meta"].iloc[0]["key"]
    block = json.loads(store.get(key).decode("utf-8"))["blocks"][0]
    assert block["width"] > 0 and block["height"] > 0
    # Every word must sit inside the page it claims to be on, or the scale is
    # being computed against the wrong rectangle.
    for w in block["words"]:
        assert 0 <= w["x0"] <= block["width"], w
        assert 0 <= w["top"] <= block["height"], w


def test_extract_meta_carries_the_key_of_its_own_artifact(corpus):
    """A row says which document it came from (`artifact_ref`) but the blocks
    live under the *derived* key. Without it on the row the inspector has no
    way to reach the boxes — the doc hash alone can't be turned back into a
    derived key without knowing the provider and every param."""
    from dte.artifacts import get_artifact_store

    engine = DuckDBEngine()
    out = _extract(engine, _documents_table(corpus, engine)).execute()
    store = get_artifact_store()

    for meta in out["extract_meta"]:
        assert store.exists(meta["key"]), meta


# ── extract: failure isolation ──────────────────────────────────────────────


def test_one_corrupt_document_does_not_fail_the_batch(corpus):
    """One bad PDF in 10k must cost one row, not the run."""
    (corpus / "corrupt.pdf").write_bytes(b"\x00 not a pdf")
    engine = DuckDBEngine()
    out = _extract(engine, _documents_table(corpus, engine)).execute()

    bad = out[out["filename"] == "corrupt.pdf"]
    assert len(bad) == 1
    assert bad.iloc[0]["content"] is None
    assert bad.iloc[0]["extract_meta"]["error"] is not None
    assert len(out[out["filename"] != "corrupt.pdf"]) == 6      # others fine


def test_missing_file_is_recorded_not_raised(corpus):
    engine = DuckDBEngine()
    table = _documents_table(corpus, engine)
    (corpus / "a.pdf").unlink()
    out = _extract(engine, table).execute()
    bad = out[out["filename"] == "a.pdf"]
    assert bad.iloc[0]["extract_meta"]["error"] is not None


def test_unknown_provider_is_rejected_at_model_validation():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractStep(op="extract", provider="nonesuch")


# ── compiler wiring ─────────────────────────────────────────────────────────


def test_extract_dispatches_through_compile_pipeline(corpus):
    engine = DuckDBEngine()
    table = _documents_table(corpus, engine)
    pipeline = Pipeline(
        id="p1", name="p1", sources=["docs"], output_id="out",
        steps=[{"op": "extract", "provider": "pdfplumber"}],
    )
    out = compile_pipeline(pipeline, {"docs": table}, engine=engine).execute()
    assert len(out) == 6


def test_extract_step_is_a_known_step_model():
    p = Pipeline(
        id="p2", name="p2", sources=["s"], output_id="o",
        steps=[{"op": "extract", "provider": "pypdf", "granularity": "document"}],
    )
    assert p.steps[0]["op"] == "extract"
