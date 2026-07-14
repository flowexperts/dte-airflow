"""Secret-resolver factory.

Selection rule (evaluated once at import time):
- `DTE_SECRETS_KEY` set → FernetSecretResolver.
- otherwise → EnvSecretResolver (dev default; `{env: X}` refs resolved at
  decrypt time from `os.environ`).

Override via `DTE_SECRETS_BACKEND=env|fernet` if you want to force one.
"""
from __future__ import annotations
import os
import warnings

from dte.secrets.base import SecretResolver
from dte.secrets.env import EnvSecretResolver


def _build_resolver() -> SecretResolver:
    backend = os.getenv("DTE_SECRETS_BACKEND")
    key = os.getenv("DTE_SECRETS_KEY")

    if backend == "env":
        return EnvSecretResolver()
    if backend == "fernet":
        if not key:
            raise RuntimeError(
                "DTE_SECRETS_BACKEND=fernet requires DTE_SECRETS_KEY to be set."
            )
        from dte.secrets.fernet import FernetSecretResolver
        return FernetSecretResolver(key)

    if key:
        from dte.secrets.fernet import FernetSecretResolver
        return FernetSecretResolver(key)

    # Prod signal: encourage setting a key. In dev it's fine to fall through.
    if os.getenv("DATABASE_URL"):
        warnings.warn(
            "DTE_SECRETS_KEY unset while DATABASE_URL is set — connection "
            "credentials will be stored as unencrypted JSON. Generate a key "
            "with `python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and set DTE_SECRETS_KEY.",
            RuntimeWarning,
            stacklevel=2,
        )
    return EnvSecretResolver()


_resolver: SecretResolver | None = None


def get_secret_resolver() -> SecretResolver:
    global _resolver
    if _resolver is None:
        _resolver = _build_resolver()
    return _resolver


__all__ = ["SecretResolver", "EnvSecretResolver", "get_secret_resolver"]
