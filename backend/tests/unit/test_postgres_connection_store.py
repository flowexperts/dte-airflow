"""PostgresConnectionStore encryption round-trip, with a mocked session.

The real DB path is covered by manual verification against a live
Postgres. Here we assert the store hands ciphertext (not plaintext) to
SQL, and reverses it via the injected SecretResolver on read.
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

from dte.secrets.fernet import FernetSecretResolver
from dte.store.postgres import PostgresConnectionStore


class _CapturingSession:
    """Async context manager that records every `execute` call's params."""
    def __init__(self):
        self.execute = AsyncMock()
        self.commit = AsyncMock()

    async def __aenter__(self):
        return self
    async def __aexit__(self, *_a):
        pass


def _factory_with(session):
    def factory():
        return session
    return factory


@pytest.fixture
def resolver():
    return FernetSecretResolver(Fernet.generate_key())


async def test_save_encrypts_before_write(resolver):
    session = _CapturingSession()
    store = PostgresConnectionStore(_factory_with(session), resolver=resolver)

    creds = {"aws_access_key_id": "AKIA", "aws_secret_access_key": "s3cret"}
    await store.save({"id": "c1", "connection_type": "s3", "credentials": creds})

    # The single execute call receives an encrypted bytes blob, not the plaintext.
    call = session.execute.call_args
    params = call[0][1]
    ciphertext = params["credentials_encrypted"]
    assert isinstance(ciphertext, bytes)
    assert b"s3cret" not in ciphertext
    assert b"AKIA" not in ciphertext
    # Round-trip: the resolver can decrypt what we handed the DB.
    assert resolver.decrypt(ciphertext) == creds


async def test_get_decrypts_stored_ciphertext(resolver):
    creds = {"aws_access_key_id": "K", "aws_secret_access_key": "S"}
    ciphertext = resolver.encrypt(creds)

    session = _CapturingSession()
    # Emulate the mappings().fetchone() chain.
    row = {"id": "c1", "connection_type": "s3", "credentials_encrypted": ciphertext}
    mappings = MagicMock()
    mappings.fetchone.return_value = row
    result = MagicMock()
    result.mappings.return_value = mappings
    session.execute.return_value = result

    store = PostgresConnectionStore(_factory_with(session), resolver=resolver)
    got = await store.get("c1")
    assert got == {"id": "c1", "connection_type": "s3", "credentials": creds}


async def test_get_missing_returns_none(resolver):
    session = _CapturingSession()
    mappings = MagicMock()
    mappings.fetchone.return_value = None
    result = MagicMock()
    result.mappings.return_value = mappings
    session.execute.return_value = result

    store = PostgresConnectionStore(_factory_with(session), resolver=resolver)
    assert await store.get("nope") is None


async def test_list_never_decrypts_credentials(resolver):
    session = _CapturingSession()
    # `list` should not touch credentials_encrypted at all.
    mappings = MagicMock()
    mappings.fetchall.return_value = [
        {"id": "c1", "connection_type": "s3"},
        {"id": "c2", "connection_type": "postgres"},
    ]
    result = MagicMock()
    result.mappings.return_value = mappings
    session.execute.return_value = result

    store = PostgresConnectionStore(_factory_with(session), resolver=resolver)
    rows = await store.list()
    assert rows == [
        {"id": "c1", "connection_type": "s3", "credentials": {}},
        {"id": "c2", "connection_type": "postgres", "credentials": {}},
    ]
    # SELECT should only pull id + connection_type — not the encrypted blob.
    sql = str(session.execute.call_args[0][0])
    assert "credentials_encrypted" not in sql
