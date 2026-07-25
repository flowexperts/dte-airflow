"""Audit-log emission on credential decrypt (P3 #36).

Asserts that EncryptedJSON.process_result_value emits a single log record
on `dte.audit.credentials` with the expected fields sourced from ContextVars.
"""
from __future__ import annotations

import logging

import pytest

from dte.logging import decrypt_context_var, request_id_var, user_id_var
from dte.secrets.encrypted_json import EncryptedJSON


@pytest.fixture()
def audit_records(caplog):
    caplog.set_level(logging.INFO, logger="dte.audit.credentials")
    yield caplog


def _decrypt_something(value: bytes) -> None:
    """Round a payload through EncryptedJSON to trigger the audit path."""
    td = EncryptedJSON()
    # The default resolver (EnvSecretResolver in test env) round-trips
    # dict → bytes → dict. Encrypt first to have a valid payload to decrypt.
    encoded = td.process_bind_param({"url": "postgres://x"}, None)
    td.process_result_value(encoded, None)


def test_decrypt_emits_audit_record(audit_records):
    request_id_var.set("req-abc")
    user_id_var.set("user-42")
    decrypt_context_var.set("pipeline_run")
    try:
        _decrypt_something(b"")
    finally:
        request_id_var.set(None)
        user_id_var.set(None)
        decrypt_context_var.set(None)

    events = [
        r for r in audit_records.records
        if r.name == "dte.audit.credentials" and getattr(r, "event", None) == "credential_decrypt"
    ]
    assert len(events) == 1
    rec = events[0]
    assert rec.decrypt_context == "pipeline_run"
    assert rec.actor_request_id == "req-abc"
    assert rec.actor_user_id == "user-42"


def test_decrypt_without_context_logs_unknown(audit_records):
    # ContextVars all unset (autouse conftest doesn't set them)
    _decrypt_something(b"")

    events = [
        r for r in audit_records.records
        if r.name == "dte.audit.credentials" and getattr(r, "event", None) == "credential_decrypt"
    ]
    assert len(events) >= 1
    assert events[-1].decrypt_context == "unknown"


def test_decrypt_of_none_does_not_audit(audit_records):
    td = EncryptedJSON()
    td.process_result_value(None, None)  # noqa — the NULL case

    events = [
        r for r in audit_records.records
        if r.name == "dte.audit.credentials" and getattr(r, "event", None) == "credential_decrypt"
    ]
    assert len(events) == 0
