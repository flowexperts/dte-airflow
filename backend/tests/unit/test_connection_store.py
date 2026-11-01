from dte.models.pipeline import Connection
from tests.fakes import FakeConnectionStore


def _conn(cid="c1") -> Connection:
    return Connection(
        id=cid,
        connection_type="s3",
        credentials={"aws_access_key_id": "AKIA", "aws_secret_access_key": "wow"},
    )


async def test_save_and_get_returns_plaintext():
    s = FakeConnectionStore()
    await s.save(_conn())
    got = await s.get("c1")
    assert isinstance(got, Connection)
    assert got.connection_type == "s3"
    assert got.credentials["aws_secret_access_key"] == "wow"


async def test_list_masks_credentials():
    s = FakeConnectionStore()
    await s.save(_conn())
    listed = await s.list()
    assert len(listed) == 1
    assert isinstance(listed[0], Connection)
    assert listed[0].credentials == {}


async def test_delete():
    s = FakeConnectionStore()
    await s.save(_conn())
    assert await s.delete("c1") is True
    assert await s.get("c1") is None
