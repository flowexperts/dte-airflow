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

import logging

from sqlalchemy.types import LargeBinary, TypeDecorator

from dte.logging import decrypt_context_var, request_id_var, user_id_var
from dte.secrets import get_secret_resolver

_audit_log = logging.getLogger("dte.audit.credentials")


class EncryptedJSON(TypeDecorator):
    """JSONB-shaped dict, encrypted at rest via the module-level SecretResolver.

    Every successful decrypt emits an audit log line on
    ``dte.audit.credentials`` (event=credential_decrypt) carrying the current
    request_id, user_id, and decrypt_context. Callers set
    ``decrypt_context_var`` to tag the reason (``pipeline_run``,
    ``connection_test``, ``reveal_api``); unset context logs as ``unknown``.
    Log platforms filter on ``event=credential_decrypt`` for access reports.
    """

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
        result = get_secret_resolver().decrypt(bytes(value))
        _audit_log.info(
            "credential_decrypt",
            extra={
                "event": "credential_decrypt",
                "decrypt_context": decrypt_context_var.get() or "unknown",
                "actor_request_id": request_id_var.get(),
                "actor_user_id": user_id_var.get(),
            },
        )
        return result
