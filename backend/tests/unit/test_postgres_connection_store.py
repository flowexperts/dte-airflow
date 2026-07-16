"""PostgresConnectionStore encryption round-trip, with a mocked session.

The real DB path is covered by manual verification against a live
Postgres. Here we assert the store hands ciphertext (not plaintext) to
SQL, and reverses it via the injected SecretResolver on read.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet

from dte.models.pipeline import Connection, ConnectionCreate
from dte.secrets.fernet import FernetSecretResolver
from dte.store.postgres import PostgresConnectionStore


class _CapturingSession:
    """Async context manager that records every `execute` call's params."""
    def __init__(self):
        self.execute = AsyncMock()
        self.commit = AsyncMock()
        self.get = AsyncMock()

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

    conn = ConnectionCreate(
        id="c1",
        connection_type="s3",
        credentials={"aws_access_key_id": "AKIA", "aws_secret_access_key": "s3cret"},
    )
    await store.save(conn)

    # The execute call receives an encrypted bytes blob in the upsert values.
    call = session.execute.call_args
    # pg_insert().on_conflict_do_update() — inspect the compiled values
    stmt = call[0][0]
    # Extract values from the INSERT statement
    compiled_params = stmt.compile().params
    ciphertext = compiled_params["credentials_encrypted"]
    assert isinstance(ciphertext, bytes)
    assert b"s3cret" not in ciphertext
    assert b"AKIA" not in ciphertext
    # Round-trip: the resolver can decrypt what we handed the DB.
    decrypted = resolver.decrypt(ciphertext)
    assert decrypted["aws_access_key_id"] == "AKIA"
    assert decrypted["aws_secret_access_key"] == "s3cret"


async def test_get_decrypts_stored_ciphertext(resolver):
    creds = {"aws_access_key_id": "K", "aws_secret_access_key": "S"}
    ciphertext = resolver.encrypt(creds)

    session = _CapturingSession()
    # Emulate session.get(Connection, id) returning an ORM row.
    db_row = Connection(
        id="c1",
        connection_type="s3",
        credentials_encrypted=ciphertext,
    )
    session.get.return_value = db_row

    store = PostgresConnectionStore(_factory_with(session), resolver=resolver)
    got = await store.get("c1")

    assert isinstance(got, Connection)
    assert got.id == "c1"
    assert got.connection_type == "s3"
    assert got.credentials_dict() == creds


async def test_get_missing_returns_none(resolver):
    session = _CapturingSession()
    session.get.return_value = None

    store = PostgresConnectionStore(_factory_with(session), resolver=resolver)
    assert await store.get("nope") is None


async def test_list_never_decrypts_credentials(resolver):
    session = _CapturingSession()
    # `list` uses select(Connection) — mock scalars().all()
    row1 = Connection(id="c1", connection_type="s3", credentials_encrypted=b"enc1")
    row2 = Connection(id="c2", connection_type="postgres", credentials_encrypted=b"enc2")

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [row1, row2]
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    session.execute.return_value = result_mock

    store = PostgresConnectionStore(_factory_with(session), resolver=resolver)
    rows = await store.list()

    assert len(rows) == 2
    assert all(isinstance(r, Connection) for r in rows)
    assert rows[0].id == "c1"
    assert rows[1].id == "c2"
    # Credentials must be masked (empty dict — no decryption).
    assert rows[0].credentials_dict() == {}
    assert rows[1].credentials_dict() == {}
    # No decryption calls should have been made to the resolver.
    # (Verify indirectly: credentials_encrypted is still the raw bytes.)
    assert rows[0].credentials_encrypted == b"enc1"
