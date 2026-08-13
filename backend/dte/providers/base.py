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


@runtime_checkable
class StructureProvider(Protocol):
    """Blocks → the user's declared data model. Implemented in plan 050 phase 2."""

    name: str

    def structure(
        self, blocks: list[Block], schema: Any, params: dict
    ) -> Any: ...
