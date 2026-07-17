"""PostgresConnectionStore — unit tests with a mocked session.

With the EncryptedJSON TypeDecorator, encryption/decryption happens at the
column level.  The store itself no longer injects a SecretResolver — it just
calls session.get / session.execute.

These tests verify:
- `save` passes a ConnectionBase/Connection to the upsert statement.
- `get` returns the Connection row as-is (EncryptedJSON handles decryption
  in real Postgres; here we just verify attribute access works).
- `list` returns rows with credentials masked to {}.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from dte.models.pipeline import Connection, ConnectionBase
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


async def test_save_accepts_connection_base():
    """save() must accept a ConnectionBase without error."""
    session = _CapturingSession()
    store = PostgresConnectionStore(_factory_with(session))

    conn = ConnectionBase(
        id="c1",
        connection_type="s3",
        credentials={"aws_access_key_id": "AKIA", "aws_secret_access_key": "s3cret"},
    )
    await store.save(conn)

    # An execute + commit call must have happened.
    assert session.execute.called
    assert session.commit.called


async def test_get_returns_connection_row():
    """get() must return the Connection row returned by session.get."""
    session = _CapturingSession()
    db_row = Connection(
        id="c1",
        connection_type="s3",
        credentials={"aws_access_key_id": "K", "aws_secret_access_key": "S"},
    )
    session.get.return_value = db_row

    store = PostgresConnectionStore(_factory_with(session))
    got = await store.get("c1")

    assert isinstance(got, Connection)
    assert got.id == "c1"
    assert got.connection_type == "s3"
    # EncryptedJSON would decrypt in real Postgres; in the unit test the
    # value is whatever we put on the ORM instance directly.
    assert got.credentials == {"aws_access_key_id": "K", "aws_secret_access_key": "S"}


async def test_get_missing_returns_none():
    session = _CapturingSession()
    session.get.return_value = None

    store = PostgresConnectionStore(_factory_with(session))
    assert await store.get("nope") is None


async def test_list_masks_credentials():
    """list() must return Connection instances with credentials={}."""
    session = _CapturingSession()
    row1 = Connection(id="c1", connection_type="s3", credentials={"aws_access_key_id": "K"})
    row2 = Connection(id="c2", connection_type="postgres", credentials={"url": "postgresql://..."})

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = [row1, row2]
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    session.execute.return_value = result_mock

    store = PostgresConnectionStore(_factory_with(session))
    rows = await store.list()

    assert len(rows) == 2
    assert all(isinstance(r, Connection) for r in rows)
    assert rows[0].id == "c1"
    assert rows[1].id == "c2"
    # Credentials must be masked (empty dict).
    assert rows[0].credentials == {}
    assert rows[1].credentials == {}
