"""Content-addressed artifact store (plan 050).

Extraction is slow and billable, so its output is cached by content hash:
re-running a pipeline over unchanged documents costs nothing, and changing a
`structure` prompt does not re-parse a single PDF.

An `s3` backend slots in beside `LocalArtifactStore` when needed — it should
reuse the credential path in `dte/sources/duckdb_secrets.py` rather than
growing a second one.
"""

from dte.artifacts.local import LocalArtifactStore
from dte.artifacts.store import (
    ArtifactStore,
    derived_key,
    doc_key,
    run_provenance_key,
    validate_key,
)

__all__ = [
    "ArtifactStore",
    "LocalArtifactStore",
    "derived_key",
    "doc_key",
    "get_artifact_store",
    "run_provenance_key",
    "validate_key",
]

DEFAULT_ARTIFACT_DIR = ".dte-artifacts"


def get_artifact_store() -> ArtifactStore:
    """Resolve the configured store.

    Reads the environment on each call rather than caching, matching
    `get_settings()` — pytest monkeypatches `DTE_ARTIFACT_DIR` between tests
    and the next call must see it.
    """
    import os

    return LocalArtifactStore(os.getenv("DTE_ARTIFACT_DIR", DEFAULT_ARTIFACT_DIR))
