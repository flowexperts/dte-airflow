"""Password hashing helpers.

Uses `bcrypt` directly (not passlib) — passlib's context probing breaks
on bcrypt >= 4.1. bcrypt has a 72-byte input limit, so we sha256-prehash
long inputs to be safe (a common idiom, matches passlib's `bcrypt_sha256`).
"""
from __future__ import annotations

import base64
import hashlib

import bcrypt


def _prehash(password: str) -> bytes:
    """SHA-256 then base64 → always 44 bytes of ASCII, well under bcrypt's 72."""
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(plain), hashed.encode("utf-8"))
    except ValueError:
        return False
