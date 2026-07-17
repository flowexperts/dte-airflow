"""EncryptedJSON — SQLAlchemy TypeDecorator that encrypts a credentials
dict at rest via the module-level SecretResolver.

Physical column type: LargeBinary (BYTEA in Postgres). The resolver
selected at startup (EnvSecretResolver in dev, FernetSecretResolver in
prod) handles the encrypt/decrypt round-trip transparently.

Usage on a SQLModel field:
    credentials: dict = SMField(
        default_factory=dict,
        sa_column=Column(EncryptedJSON, nullable=False),
    )
"""
from __future__ import annotations

from sqlalchemy.types import TypeDecorator, LargeBinary

from dte.secrets import get_secret_resolver


class EncryptedJSON(TypeDecorator):
    """JSONB-shaped dict, encrypted at rest via the module-level SecretResolver."""

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value, dialect):
        """Encrypt dict → bytes before INSERT/UPDATE."""
        if value is None:
            return None
        return get_secret_resolver().encrypt(value if isinstance(value, dict) else {})

    def process_result_value(self, value, dialect):
        """Decrypt bytes → dict after SELECT."""
        if value is None:
            return {}
        return get_secret_resolver().decrypt(bytes(value))
