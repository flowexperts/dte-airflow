"""FernetSecretResolver — symmetric encryption at rest.

Key comes from `DTE_SECRETS_KEY` (URL-safe base64 Fernet key). Generate
one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Rotating the key requires re-encrypting every Connection row — not
handled here; a follow-up script will address it if it becomes needed.
"""
from __future__ import annotations
import json


class FernetSecretResolver:
    def __init__(self, key: str | bytes):
        # Imported lazily so dev environments without cryptography can still
        # load the module (the env resolver has no such requirement).
        from cryptography.fernet import Fernet

        self._fernet = Fernet(key if isinstance(key, bytes) else key.encode("utf-8"))

    def encrypt(self, plaintext: dict) -> bytes:
        return self._fernet.encrypt(json.dumps(plaintext).encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> dict:
        raw = self._fernet.decrypt(ciphertext)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("fernet resolver: stored payload must be a dict")
        return payload
