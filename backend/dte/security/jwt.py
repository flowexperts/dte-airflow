"""JWT encode/decode helpers.

HS256 signing. Secret from `DTE_JWT_SECRET`; TTL from `DTE_JWT_TTL_SECONDS`
(default 24h). Startup hard-fail if secret is missing when `DATABASE_URL`
is set (production signal); dev falls back to a deterministic placeholder
with a warning.
"""
from __future__ import annotations

import os
import time
import warnings

import jwt as _jwt

_ALGO = "HS256"
_DEV_FALLBACK_SECRET = "dte-dev-insecure-jwt-secret-do-not-use-in-prod"


def _secret() -> str:
    s = os.getenv("DTE_JWT_SECRET")
    if s:
        return s
    if os.getenv("DATABASE_URL"):
        raise RuntimeError(
            "DTE_JWT_SECRET must be set when DATABASE_URL is set (production). "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    warnings.warn(
        "DTE_JWT_SECRET not set; using an insecure dev fallback. "
        "This is only safe for local development.",
        stacklevel=2,
    )
    return _DEV_FALLBACK_SECRET


def _ttl_seconds() -> int:
    return int(os.getenv("DTE_JWT_TTL_SECONDS", str(24 * 60 * 60)))


def create_access_token(*, user_id: str, email: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + _ttl_seconds(),
    }
    return _jwt.encode(payload, _secret(), algorithm=_ALGO)


def decode_access_token(token: str) -> dict:
    """Return the JWT payload. Raises `jwt.PyJWTError` on any failure
    (expired, invalid signature, malformed). Callers should catch it
    and translate to a 401."""
    return _jwt.decode(token, _secret(), algorithms=[_ALGO])
