"""Filesystem-backed artifact store.

Layout shards on the first two byte-pairs of the key:

    <root>/ab/cd/abcd…ef.bin      the content
    <root>/ab/cd/abcd…ef.meta     the media type

A flat directory holding 100k documents is a filesystem problem on every OS
worth supporting, so the fan-out is not optional.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO

from dte.artifacts.store import validate_key


class LocalArtifactStore:
    """`ArtifactStore` over a local directory tree.

    The root is created lazily on first write — constructing a store must not
    touch the filesystem, so importing the module in a test that never stores
    anything stays free.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    # ── paths ───────────────────────────────────────────────────────────────

    def _dir(self, key: str) -> Path:
        return self.root / key[0:2] / key[2:4]

    def _blob(self, key: str) -> Path:
        return self._dir(key) / f"{key}.bin"

    def _meta(self, key: str) -> Path:
        return self._dir(key) / f"{key}.meta"

    # ── protocol ────────────────────────────────────────────────────────────

    def put(self, key: str, content: bytes, media_type: str) -> str:
        validate_key(key)
        blob = self._blob(key)
        if not blob.exists():
            blob.parent.mkdir(parents=True, exist_ok=True)
            # Write to a temp name in the same directory and rename, so a
            # crash mid-write can't leave a truncated blob under a key that
            # `exists()` would then report as present.
            tmp = blob.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_bytes(content)
            tmp.replace(blob)
            self._meta(key).write_text(media_type, encoding="utf-8")
        return f"artifact://{key}"

    def get(self, key: str) -> bytes:
        validate_key(key)
        try:
            return self._blob(key).read_bytes()
        except FileNotFoundError as exc:
            raise KeyError(f"no artifact stored under {key}") from exc

    def exists(self, key: str) -> bool:
        validate_key(key)
        return self._blob(key).exists()

    def media_type(self, key: str) -> str | None:
        validate_key(key)
        try:
            return self._meta(key).read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None

    def open_stream(self, key: str) -> IO[bytes]:
        validate_key(key)
        try:
            return self._blob(key).open("rb")
        except FileNotFoundError as exc:
            raise KeyError(f"no artifact stored under {key}") from exc
