"""Content-addressed artifact storage — protocol and key derivation.

Two key forms, and the distinction between them is the economic argument for
plan 050's two-op split:

    doc_key     = sha256(document bytes)
    derived_key = sha256(doc_key | op | provider | canonical(params))

Because a `structure` prompt change alters the derived key for `structure` but
not the one for `extract`, PDF parsing is paid once and every prompt variant
thereafter costs only the model call it actually needs.

Keys are content hashes, so a document that moves or gets renamed keeps its
identity — which is also why plan 051's labels join on `doc_key`.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import IO, Any, Protocol, runtime_checkable

# Keys are lowercase hex sha256. Validated on every call because they arrive
# from URL path segments — an unvalidated key is a path-traversal primitive.
_KEY_RE = re.compile(r"^[0-9a-f]{64}$")


def validate_key(key: str) -> str:
    if not isinstance(key, str) or not _KEY_RE.match(key):
        raise ValueError(
            f"invalid artifact key {key!r}: expected 64 lowercase hex characters"
        )
    return key


def doc_key(content: bytes) -> str:
    """Identity of a source document: sha256 of its bytes."""
    return hashlib.sha256(content).hexdigest()


def run_provenance_key(run_id: str) -> str:
    """Key for a run's provenance sidecar.

    Derived from the run id rather than from content, so the API can find it
    with nothing stored in the database — no column, no migration. The
    store's immutability contract still holds: a completed run's provenance
    never changes, so the bytes under this key never change either.

    Namespaced so it can never collide with a document hash.
    """
    return hashlib.sha256(f"dte:run-provenance:{run_id}".encode()).hexdigest()


def _canonical(params: Any) -> str:
    """Order-insensitive, stable JSON. A dict built in a different order must
    hash the same or the cache would miss constantly."""
    return json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)


def derived_key(
    source_key: str, op: str, provider: str, params: Any | None = None
) -> str:
    """Identity of anything computed *from* a document.

    Changing any input — document, op, provider, or a single param — yields a
    different key, so a cache hit is a genuine "same question, same answer".
    """
    payload = "\x1f".join([source_key, op, provider, _canonical(params or {})])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@runtime_checkable
class ArtifactStore(Protocol):
    """Blob storage keyed by content hash.

    Rows never carry blobs — they carry `artifact://<key>` refs, and the UI
    streams bytes back through `GET /api/artifacts/{key}`.
    """

    def put(self, key: str, content: bytes, media_type: str) -> str:
        """Store `content` under `key`; returns its `artifact://` URI.
        Idempotent — writing the same key twice is a no-op, not an error."""
        ...

    def get(self, key: str) -> bytes:
        """Raises `KeyError` when absent."""
        ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> bool:
        """Drop `key`. Returns whether anything was there. Absent is not an
        error — deletion is idempotent, and eviction races itself."""
        ...

    def media_type(self, key: str) -> str | None: ...

    def size(self, key: str) -> int:
        """Byte length, without reading the content. Raises `KeyError` when
        absent. Range responses need the total to build `Content-Range`, and
        reading the blob to measure it would defeat the point."""
        ...

    def open_stream(self, key: str) -> IO[bytes]:
        """File-like handle, so large artifacts don't have to be fully
        materialised to be served."""
        ...
