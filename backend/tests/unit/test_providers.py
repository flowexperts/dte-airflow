"""Extract providers: bytes in, blocks out.

Deterministic and free — no model, no network. These are the providers that
make the 050 loop usable before any API key exists.
"""

import pytest

from dte.providers import (
    ProviderNotAvailable,
    UnknownProvider,
    extract_provider,
    list_extract_providers,
)
from tests.fixtures.pdf_builder import build_pdf

PAGES = ["Invoice total 1240.50", "Vendor Acme Industrial", "Issued 2024-03-01"]


@pytest.fixture
def pdf() -> bytes:
    return build_pdf(PAGES)


@pytest.fixture(params=["pypdf", "pdfplumber"])
def provider(request):
    return extract_provider(request.param)


# ── registry ────────────────────────────────────────────────────────────────


def test_registry_lists_the_deterministic_providers():
    assert {"pypdf", "pdfplumber"} <= set(list_extract_providers())


def test_unknown_provider_names_the_alternatives():
    with pytest.raises(UnknownProvider) as exc:
        extract_provider("nonesuch")
    assert "pypdf" in str(exc.value)


def test_provider_reports_its_own_name():
    assert extract_provider("pypdf").name == "pypdf"


# ── page granularity ────────────────────────────────────────────────────────


def test_page_granularity_yields_one_block_per_page(provider, pdf):
    result = provider.extract(pdf, "application/pdf", {"granularity": "page"})
    assert result.error is None
    assert len(result.blocks) == 3
    assert [b.page for b in result.blocks] == [1, 2, 3]
    assert [b.index for b in result.blocks] == [0, 1, 2]


def test_page_text_is_extracted_verbatim(provider, pdf):
    result = provider.extract(pdf, "application/pdf", {"granularity": "page"})
    assert [b.text.strip() for b in result.blocks] == PAGES


def test_document_granularity_yields_one_block(provider, pdf):
    result = provider.extract(pdf, "application/pdf", {"granularity": "document"})
    assert len(result.blocks) == 1
    assert result.blocks[0].page is None
    for page_text in PAGES:
        assert page_text in result.blocks[0].text


def test_default_granularity_is_page(provider, pdf):
    assert len(provider.extract(pdf, "application/pdf", {}).blocks) == 3


def test_unknown_granularity_raises(provider, pdf):
    with pytest.raises(ValueError):
        provider.extract(pdf, "application/pdf", {"granularity": "molecule"})


# ── provenance ──────────────────────────────────────────────────────────────


def test_pdfplumber_emits_word_bboxes(pdf):
    """Provenance is mandatory — it's what lets the inspector highlight the
    source of a value on the rendered page."""
    result = extract_provider("pdfplumber").extract(pdf, "application/pdf", {})
    first = result.blocks[0]
    assert first.bbox is not None
    assert set(first.bbox) == {"x0", "top", "x1", "bottom"}
    assert first.bbox["x1"] > first.bbox["x0"]
    assert first.bbox["bottom"] > first.bbox["top"]

    assert first.words, "pdfplumber must expose per-word boxes for char spans"
    word = first.words[0]
    assert word["text"] == "Invoice"
    assert word["x0"] == pytest.approx(72.0, abs=0.5)


def test_pypdf_reports_no_bbox_rather_than_faking_one(pdf):
    """pypdf has no layout information. Inventing a box would make the
    inspector point at the wrong place, which is worse than pointing nowhere."""
    result = extract_provider("pypdf").extract(pdf, "application/pdf", {})
    assert result.blocks[0].bbox is None
    assert result.blocks[0].words == []


# ── failure handling ────────────────────────────────────────────────────────


def test_corrupt_pdf_returns_an_error_rather_than_raising(provider):
    """One bad PDF in 10k must not cost you the batch — the step records the
    error on the row and carries on."""
    result = provider.extract(b"not a pdf at all", "application/pdf", {})
    assert result.error is not None
    assert result.blocks == []


def test_empty_input_is_an_error_not_a_crash(provider):
    result = provider.extract(b"", "application/pdf", {})
    assert result.error is not None


def test_unsupported_media_type_is_rejected(provider, pdf):
    result = provider.extract(pdf, "audio/mpeg", {})
    assert result.error is not None
    assert "audio/mpeg" in result.error


# ── determinism + metadata ──────────────────────────────────────────────────


def test_extraction_is_deterministic(provider, pdf):
    a = provider.extract(pdf, "application/pdf", {})
    b = provider.extract(pdf, "application/pdf", {})
    assert [x.text for x in a.blocks] == [x.text for x in b.blocks]


def test_result_records_provider_and_elapsed(provider, pdf):
    result = provider.extract(pdf, "application/pdf", {})
    assert result.provider == provider.name
    assert result.elapsed_ms >= 0


def test_missing_optional_dependency_reports_the_extra(monkeypatch):
    """A missing dep must be an actionable message naming the extra, not an
    ImportError from three frames down."""
    import dte.providers.pdf as pdf_mod

    monkeypatch.setattr(pdf_mod, "_import_pypdf", lambda: (_ for _ in ()).throw(
        ImportError("No module named 'pypdf'")
    ))
    result = extract_provider("pypdf").extract(build_pdf(["x"]), "application/pdf", {})
    assert result.error is not None
    assert "unstructured" in result.error


def test_provider_not_available_is_raisable():
    assert issubclass(ProviderNotAvailable, Exception)
