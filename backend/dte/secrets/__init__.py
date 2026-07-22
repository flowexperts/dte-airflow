"""Secret-resolver factory.

Selection rule (evaluated at first call):
- `DTE_SECRETS_BACKEND=env` → EnvSecretResolver
- `DTE_SECRETS_BACKEND=fernet` → FernetSecretResolver (requires DTE_SECRETS_KEY)
- otherwise: DTE_SECRETS_KEY set → Fernet; else Env.

Reads via `dte.config.Settings` so overrides survive test env manipulation.
"""
from __future__ import annotations

import warnings

from dte.config import get_settings
from dte.secrets.base import SecretResolver
from dte.secrets.env import EnvSecretResolver


def _build_resolver() -> SecretResolver:
    s = get_settings()
    backend = s.secrets_backend
    key = s.secrets_key

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

    if s.database_url:
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


def reset_secret_resolver() -> None:
    """Test hook — force a rebuild on next `get_secret_resolver()` call."""
    global _resolver
    _resolver = None


__all__ = [
    "SecretResolver",
    "EnvSecretResolver",
    "get_secret_resolver",
    "reset_secret_resolver",
]
