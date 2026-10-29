"""Provider contracts for the enrichment ops.

Shaped like `sources/loader.py`'s `LOADERS` — a flat name→instance registry,
not a class hierarchy. Adding a provider is one module plus one entry.

Two rules every provider obeys:

1. **Never raise for bad input.** A corrupt document returns an `ExtractResult`
   carrying `error`, so one bad PDF in 10k costs one row rather than the batch.
   Programming errors (an unknown granularity) still raise.
2. **Emit provenance or admit you have none.** `bbox`/`words` may be empty, but
   they must never be invented — the inspector points at whatever a provider
   claims, and a wrong highlight is worse than no highlight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class UnknownProvider(ValueError):
    """No provider registered under that name."""


class ProviderNotAvailable(RuntimeError):
    """The provider's optional dependency isn't installed."""


@dataclass(frozen=True)
class Block:
    """One unit of extracted content — a page, or a whole document."""

    text: str
    index: int
    page: int | None = None
    # Bounding box of the block's content, in PDF points, or None when the
    # provider has no layout information.
    bbox: dict[str, float] | None = None
    # Per-word boxes, used to resolve a character span to a highlight.
    words: list[dict[str, Any]] = field(default_factory=list)
    # The page's own size in PDF points. Word boxes are meaningless without
    # it: rendering needs a scale factor, and `bbox` describes the content,
    # not the page, so a page with margins would scale wrong.
    width: float | None = None
    height: float | None = None


@dataclass(frozen=True)
class ExtractResult:
    blocks: list[Block]
    provider: str
    elapsed_ms: int = 0
    cached: bool = False
    error: str | None = None


@runtime_checkable
class ExtractProvider(Protocol):
    name: str

    def extract(
        self, doc: bytes, media_type: str, params: dict
    ) -> ExtractResult: ...


@dataclass(frozen=True)
class FieldSpec:
    """One column the user wants extracted.

    `description` is the primary steering signal for model-backed providers —
    it is what the model reads to decide what to look for. `pattern` is only
    consulted by the deterministic `regex` provider.
    """

    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    examples: list[str] = field(default_factory=list)
    pattern: str | None = None


@dataclass(frozen=True)
class DataModel:
    fields: list[FieldSpec]
    instructions: str = ""


@dataclass(frozen=True)
class StructureResult:
    """Values plus the provenance that makes them checkable.

    `provenance[name]` is `{confidence, page, char_start, char_end, quote}` or
    None. It is what lets the inspector highlight where a value came from —
    the difference between "the model said 1240.50" and "I can see where it
    got 1240.50".
    """

    values: dict[str, Any]
    provenance: dict[str, dict | None]
    provider: str
    blocks_text: str = ""
    elapsed_ms: int = 0
    cached: bool = False
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


@runtime_checkable
class StructureProvider(Protocol):
    name: str

    def structure(
        self, blocks: list[Block], model: DataModel, params: dict, client=None
    ) -> StructureResult: ...
