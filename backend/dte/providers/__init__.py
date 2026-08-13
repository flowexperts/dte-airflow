"""Provider registry for the enrichment ops (plan 050).

Flat name→instance dicts, deliberately shaped like `sources/loader.py`'s
`LOADERS`. Adding a provider is one module plus one entry here.

Phase 1 ships only the deterministic, offline extractors — they cost nothing,
need no credentials, and are enough to make the whole extract loop usable
before an API key exists. Model-backed providers (`claude`, `openai`) and the
`structure` side land in phase 2.
"""

from dte.providers.base import (
    Block,
    ExtractProvider,
    ExtractResult,
    ProviderNotAvailable,
    StructureProvider,
    UnknownProvider,
)
from dte.providers.pdf import PdfplumberProvider, PypdfProvider

__all__ = [
    "Block",
    "ExtractProvider",
    "ExtractResult",
    "ProviderNotAvailable",
    "StructureProvider",
    "UnknownProvider",
    "extract_provider",
    "list_extract_providers",
]

EXTRACT_PROVIDERS: dict[str, ExtractProvider] = {
    "pypdf": PypdfProvider(),
    "pdfplumber": PdfplumberProvider(),
}

STRUCTURE_PROVIDERS: dict[str, StructureProvider] = {}


def list_extract_providers() -> list[str]:
    return sorted(EXTRACT_PROVIDERS)


def extract_provider(name: str) -> ExtractProvider:
    try:
        return EXTRACT_PROVIDERS[name]
    except KeyError:
        raise UnknownProvider(
            f"unknown extract provider {name!r}; "
            f"available: {', '.join(list_extract_providers())}"
        ) from None
