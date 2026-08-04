from tests.fakes import FakeDestinationStore
from dte.models.pipeline import DestinationCreate


def _dest(did: str) -> DestinationCreate:
    return DestinationCreate(
        id=did,
        connection_id="local_fs",
        config={"type": "json_file", "path": f"/tmp/{did}.json"},
    )


async def test_save_and_get():
    s = FakeDestinationStore()
    await s.save(_dest("d1"))
    got = await s.get("d1")
    assert got is not None
    assert got.id == "d1"
    assert got.config.type == "json"  # legacy "json_file" input normalises to the format-only name


async def test_get_missing_returns_none():
    s = FakeDestinationStore()
    assert await s.get("nope") is None


async def test_list_pagination():
    s = FakeDestinationStore()
    for i in range(5):
        await s.save(_dest(f"d{i}"))
    page1 = await s.list(limit=3, offset=0)
    assert len(page1) == 3
    page2 = await s.list(limit=3, offset=3)
    assert len(page2) == 2


async def test_delete():
    s = FakeDestinationStore()
    await s.save(_dest("d1"))
    assert await s.delete("d1") is True
    assert await s.get("d1") is None


async def test_delete_missing_returns_false():
    s = FakeDestinationStore()
    assert await s.delete("nope") is False
