"""Deterministic PDF text extraction.

Two providers with a deliberate split of responsibilities:

- **pypdf** — fastest, fewest dependencies, text only. No layout information,
  so no provenance.
- **pdfplumber** — slower, but exposes per-word bounding boxes, which is what
  makes "click a field, highlight the source on the page" possible.

Both are free and offline. Imports are lazy so a deployment that never touches
documents doesn't carry the dependency, and a missing one produces an
actionable message naming the extra rather than an ImportError three frames
down.
"""

from __future__ import annotations

import io
import time
from typing import Any

from dte.providers.base import Block, ExtractResult

PDF_MEDIA_TYPES = {"application/pdf", "application/x-pdf"}
_GRANULARITIES = {"page", "document"}
_MISSING_DEP = (
    "{lib} is not installed — install the optional extra with "
    '`pip install "dte-airflow[unstructured]"`'
)


def _import_pypdf():
    import pypdf

    return pypdf


def _import_pdfplumber():
    import pdfplumber

    return pdfplumber


def _check_granularity(params: dict) -> str:
    granularity = params.get("granularity", "page")
    if granularity not in _GRANULARITIES:
        # A programming error, not bad input — raise rather than record.
        raise ValueError(
            f"unknown granularity {granularity!r}; "
            f"expected one of {', '.join(sorted(_GRANULARITIES))}"
        )
    return granularity


def _reject_media_type(media_type: str) -> str | None:
    if media_type and media_type.lower() not in PDF_MEDIA_TYPES:
        return f"unsupported media type {media_type!r} for a PDF provider"
    return None


def _as_document(
    pages: list[str],
    words: list[dict[str, Any]],
    width: float | None = None,
    height: float | None = None,
) -> list[Block]:
    return [
        Block(
            text="\n\n".join(pages),
            index=0,
            page=None,
            words=words,
            width=width,
            height=height,
        )
    ]


class PypdfProvider:
    """Text-only extraction. Fast, no provenance."""

    name = "pypdf"

    def extract(self, doc: bytes, media_type: str, params: dict) -> ExtractResult:
        granularity = _check_granularity(params)
        started = time.perf_counter()

        def done(blocks: list[Block], error: str | None = None) -> ExtractResult:
            return ExtractResult(
                blocks=blocks,
                provider=self.name,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                error=error,
            )

        bad_type = _reject_media_type(media_type)
        if bad_type:
            return done([], bad_type)

        try:
            pypdf = _import_pypdf()
        except ImportError:
            return done([], _MISSING_DEP.format(lib="pypdf"))

        try:
            reader = pypdf.PdfReader(io.BytesIO(doc))
            pages = [(page.extract_text() or "") for page in reader.pages]
        except Exception as exc:  # noqa: BLE001 — any parse failure is one bad row
            return done([], f"pypdf could not read the document: {exc}")

        if not pages:
            return done([], "document contains no pages")

        if granularity == "document":
            return done(_as_document(pages, []))
        return done(
            [Block(text=t, index=i, page=i + 1) for i, t in enumerate(pages)]
        )


class PdfplumberProvider:
    """Text plus per-word bounding boxes — the provenance-capable extractor."""

    name = "pdfplumber"

    def extract(self, doc: bytes, media_type: str, params: dict) -> ExtractResult:
        granularity = _check_granularity(params)
        started = time.perf_counter()

        def done(blocks: list[Block], error: str | None = None) -> ExtractResult:
            return ExtractResult(
                blocks=blocks,
                provider=self.name,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                error=error,
            )

        bad_type = _reject_media_type(media_type)
        if bad_type:
            return done([], bad_type)

        try:
            pdfplumber = _import_pdfplumber()
        except ImportError:
            return done([], _MISSING_DEP.format(lib="pdfplumber"))

        try:
            texts: list[str] = []
            per_page_words: list[list[dict[str, Any]]] = []
            sizes: list[tuple[float, float]] = []
            with pdfplumber.open(io.BytesIO(doc)) as pdf:
                for page in pdf.pages:
                    texts.append(page.extract_text() or "")
                    sizes.append((float(page.width), float(page.height)))
                    per_page_words.append(
                        [
                            {
                                "text": w["text"],
                                "x0": float(w["x0"]),
                                "top": float(w["top"]),
                                "x1": float(w["x1"]),
                                "bottom": float(w["bottom"]),
                            }
                            for w in page.extract_words()
                        ]
                    )
        except Exception as exc:  # noqa: BLE001
            return done([], f"pdfplumber could not read the document: {exc}")

        if not texts:
            return done([], "document contains no pages")

        if granularity == "document":
            flat = [w for page_words in per_page_words for w in page_words]
            # One block spanning pages of possibly different sizes has no
            # single page size. Report the first rather than inventing a
            # composite — the inspector renders per page anyway.
            w0, h0 = sizes[0]
            return done(_as_document(texts, flat, w0, h0))

        return done(
            [
                Block(
                    text=text,
                    index=i,
                    page=i + 1,
                    bbox=_bounds(words),
                    words=words,
                    width=size[0],
                    height=size[1],
                )
                for i, (text, words, size) in enumerate(
                    zip(texts, per_page_words, sizes)
                )
            ]
        )


def _bounds(words: list[dict[str, Any]]) -> dict[str, float] | None:
    """Union box over every word on the page, or None when the page is blank.

    None rather than a zero-size box: "no content here" and "content at the
    origin" must not look the same to the inspector.
    """
    if not words:
        return None
    return {
        "x0": min(w["x0"] for w in words),
        "top": min(w["top"] for w in words),
        "x1": max(w["x1"] for w in words),
        "bottom": max(w["bottom"] for w in words),
    }
