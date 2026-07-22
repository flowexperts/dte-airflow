"""SecretResolver seam.

Every resolver knows how to round-trip a credentials dict through some
storage medium:
- `encrypt` — plaintext dict → opaque bytes to persist in the DB.
- `decrypt` — those bytes → plaintext dict ready to hand to a loader.

The env resolver skips encryption and instead resolves `{env: "VAR"}`
values at decrypt time. The fernet resolver does real symmetric
encryption. External adapters (Vault, AWS SM) can slot in later without
touching loaders or writers.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretResolver(Protocol):
    def encrypt(self, plaintext: dict) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> dict: ...
