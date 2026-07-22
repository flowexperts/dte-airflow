"""EnvSecretResolver — no real encryption; walks the dict at decrypt time
resolving any `{env: "VAR_NAME"}` value from `os.environ`. Preserves the
plan-014 UX so dev without Postgres still works.
"""
from __future__ import annotations

import json
import os
from typing import Any


def _resolve_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value.keys()) == {"env"}:
        var = value["env"]
        try:
            return os.environ[var]
        except KeyError:
            raise KeyError(f"env resolver: environment variable {var!r} is not set")
    if isinstance(value, dict):
        return {k: _resolve_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_value(v) for v in value]
    return value


class EnvSecretResolver:
    """`encrypt` is identity (JSON bytes). `decrypt` resolves env refs."""

    def encrypt(self, plaintext: dict) -> bytes:
        return json.dumps(plaintext).encode("utf-8")

    def decrypt(self, ciphertext: bytes) -> dict:
        raw = json.loads(ciphertext.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("env resolver: stored payload must be a dict")
        return _resolve_value(raw)
