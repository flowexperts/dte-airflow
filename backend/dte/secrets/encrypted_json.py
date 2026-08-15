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
_logger = logging.getLogger("dte.secrets.encrypted_json")


class UnreadableCredentials(dict):
    """Sentinel returned in place of a row's `credentials` dict when the
    stored ciphertext could not be decrypted/parsed by the *current*
    resolver (wrong secrets key, resolver-type mismatch, corruption).

    Deliberately a `dict` subclass with no keys so it behaves exactly like
    an "empty credentials" value everywhere a plain dict is read (masking,
    `bool(...)` checks, `for k in credentials`) — it can never be confused
    with real credentials because it never carries any.

    Carries the *original* ciphertext bytes so that `process_bind_param`
    can write them back unchanged on a round-trip save (e.g. `PUT` with
    credentials omitted, which re-saves whatever `credentials` already
    held) instead of silently overwriting the original ciphertext with an
    encryption of this sentinel.
    """

    unreadable = True

    def __init__(self, raw_ciphertext: bytes, reason: str = ""):
        super().__init__()
        self.raw_ciphertext = raw_ciphertext
        self.reason = reason


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
        """Encrypt dict → bytes before INSERT/UPDATE.

        A row whose credentials failed to decrypt (`UnreadableCredentials`)
        must round-trip its original ciphertext unchanged rather than being
        re-encrypted — encrypting the empty sentinel would permanently
        destroy the original (possibly still-recoverable, e.g. after a key
        rotation is reverted) ciphertext.
        """
        if value is None:
            return None
        if isinstance(value, UnreadableCredentials):
            return value.raw_ciphertext
        return get_secret_resolver().encrypt(value if isinstance(value, dict) else {})

    def process_result_value(self, value, dialect):
        """Decrypt bytes → dict after SELECT.

        Never raises: a single row encrypted under a stale key (or written
        by a different resolver type) must not take down the whole SELECT
        it's part of — that would 500 endpoints like `GET /api/connections`
        for every row, not just the bad one. Failures degrade to
        `UnreadableCredentials`, logged with no credential content.
        """
        if value is None:
            return {}
        raw = bytes(value)
        try:
            result = get_secret_resolver().decrypt(raw)
        except Exception as e:
            _logger.warning(
                "credentials failed to decrypt/parse (%s: %s) — returning "
                "unreadable-credentials sentinel",
                type(e).__name__,
                e,
            )
            return UnreadableCredentials(raw, reason=f"{type(e).__name__}: {e}")
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
