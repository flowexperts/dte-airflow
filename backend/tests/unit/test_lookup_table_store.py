from dte.models.pipeline import LookupTableBase
from tests.fakes import FakeLookupTableStore


def _lt(lid: str, mappings=None, default=None) -> LookupTableBase:
    return LookupTableBase(
        id=lid,
        name=f"{lid}-name",
        mappings=mappings or {"US": "United States"},
        default=default,
    )


async def test_save_and_get():
    s = FakeLookupTableStore()
    await s.save(_lt("country_names"))
    got = await s.get("country_names")
    assert got.id == "country_names"
    assert got.mappings == {"US": "United States"}
    assert got.name == "country_names-name"


async def test_get_missing_returns_none():
    s = FakeLookupTableStore()
    assert await s.get("nope") is None


async def test_list_pagination():
    s = FakeLookupTableStore()
    for i in range(5):
        await s.save(_lt(f"l{i}"))
    page1 = await s.list(limit=3, offset=0)
    assert len(page1) == 3
    page2 = await s.list(limit=3, offset=3)
    assert len(page2) == 2


async def test_delete():
    s = FakeLookupTableStore()
    await s.save(_lt("l1"))
    assert await s.delete("l1") is True
    assert await s.get("l1") is None


async def test_delete_missing_returns_false():
    s = FakeLookupTableStore()
    assert await s.delete("nope") is False


async def test_update_replaces_mappings():
    s = FakeLookupTableStore()
    await s.save(_lt("l1", mappings={"US": "United States"}))
    await s.save(_lt("l1", mappings={"CA": "Canada"}, default="X"))
    got = await s.get("l1")
    assert got.mappings == {"CA": "Canada"}
    assert got.default == "X"
