from dte.store.memory import MemoryDestinationStore


def _dest(did: str) -> dict:
    return {
        "id": did,
        "config": {"type": "json_file", "path": f"/tmp/{did}.json"},
    }


async def test_save_and_get():
    s = MemoryDestinationStore()
    await s.save(_dest("d1"))
    got = await s.get("d1")
    assert got["id"] == "d1"
    assert got["config"]["type"] == "json_file"


async def test_get_missing_returns_none():
    s = MemoryDestinationStore()
    assert await s.get("nope") is None


async def test_list_pagination():
    s = MemoryDestinationStore()
    for i in range(5):
        await s.save(_dest(f"d{i}"))
    page1 = await s.list(limit=3, offset=0)
    assert len(page1) == 3
    page2 = await s.list(limit=3, offset=3)
    assert len(page2) == 2


async def test_delete():
    s = MemoryDestinationStore()
    await s.save(_dest("d1"))
    assert await s.delete("d1") is True
    assert await s.get("d1") is None


async def test_delete_missing_returns_false():
    s = MemoryDestinationStore()
    assert await s.delete("nope") is False
