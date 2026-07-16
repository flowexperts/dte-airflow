from dte.models.pipeline import SourceCreate
from tests.fakes import FakeSourceStore


def _src(sid: str) -> SourceCreate:
    return SourceCreate(
        id=sid,
        connection_id="local_fs",
        source_type="filesystem",
        config={"bucket_url": "/tmp"},
        table=f"{sid}_t",
    )


async def test_save_and_get():
    s = FakeSourceStore()
    await s.save(_src("s1"))
    got = await s.get("s1")
    assert got.id == "s1"
    assert got.source_type == "filesystem"
    assert got.table == "s1_t"


async def test_get_missing_returns_none():
    s = FakeSourceStore()
    assert await s.get("nope") is None


async def test_list_pagination():
    s = FakeSourceStore()
    for i in range(5):
        await s.save(_src(f"s{i}"))
    page1 = await s.list(limit=3, offset=0)
    assert len(page1) == 3
    page2 = await s.list(limit=3, offset=3)
    assert len(page2) == 2


async def test_delete():
    s = FakeSourceStore()
    await s.save(_src("s1"))
    assert await s.delete("s1") is True
    assert await s.get("s1") is None


async def test_delete_missing_returns_false():
    s = FakeSourceStore()
    assert await s.delete("nope") is False
