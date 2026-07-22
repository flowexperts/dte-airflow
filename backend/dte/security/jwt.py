"""JWT encode/decode helpers.

HS256 signing. Secret + TTL sourced from `dte.config.Settings`. Production
signal: when `DATABASE_URL` is set but `DTE_JWT_SECRET` is missing, hard-fail
at first use; dev falls back to a deterministic placeholder with a warning.
"""
from __future__ import annotations

import time
import warnings

import jwt as _jwt

from dte.config import get_settings

_ALGO = "HS256"
_DEV_FALLBACK_SECRET = "dte-dev-insecure-jwt-secret-do-not-use-in-prod"


def _secret() -> str:
    s = get_settings()
    if s.jwt_secret:
        return s.jwt_secret
    if s.database_url:
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
    return get_settings().jwt_ttl_seconds


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
