from tests.fakes import FakeLookupTableStore
from scripts.migrate_extract_lookups import _migrate_pipeline, _dedupe_id


class _P:
    def __init__(self, id, steps):
        self.id = id
        self.name = id
        self.sources = ["s1"]
        self.output_id = "d1"
        self.steps = steps


async def test_inline_table_extracted_to_lookup_row():
    lt = FakeLookupTableStore()
    p = _P("p1", steps=[
        {"op": "map", "mode": "lookup", "field": "cc",
         "table": {"US": "United States"}, "default": "Unknown"},
    ])
    new_steps, changed = await _migrate_pipeline(p, lt, log=[])
    assert changed
    step = new_steps[0]
    assert "table" not in step and "default" not in step
    assert step["lookup_id"].startswith("lookup_")
    row = await lt.get(step["lookup_id"])
    assert row.mappings == {"US": "United States"}
    assert row.default == "Unknown"


async def test_duplicate_mappings_dedupe():
    lt = FakeLookupTableStore()
    p1 = _P("p1", steps=[
        {"op": "map", "mode": "lookup", "field": "cc",
         "table": {"US": "United States"}, "default": None},
    ])
    p2 = _P("p2", steps=[
        {"op": "map", "mode": "lookup", "field": "cc",
         "table": {"US": "United States"}, "default": None},
    ])
    s1, _ = await _migrate_pipeline(p1, lt, log=[])
    s2, _ = await _migrate_pipeline(p2, lt, log=[])
    assert s1[0]["lookup_id"] == s2[0]["lookup_id"]
    all_rows = await lt.list(limit=100)
    assert len(all_rows) == 1


async def test_already_migrated_step_untouched():
    lt = FakeLookupTableStore()
    p = _P("p1", steps=[
        {"op": "map", "mode": "lookup", "field": "cc",
         "lookup_id": "prebaked"},
    ])
    new_steps, changed = await _migrate_pipeline(p, lt, log=[])
    assert not changed
    assert new_steps[0]["lookup_id"] == "prebaked"


async def test_non_lookup_steps_pass_through():
    lt = FakeLookupTableStore()
    p = _P("p1", steps=[
        {"op": "filter", "expr": "x > 0"},
        {"op": "map", "mode": "expression", "output_field": "y", "expr": "x + 1"},
    ])
    new_steps, changed = await _migrate_pipeline(p, lt, log=[])
    assert not changed
    assert new_steps == p.steps


async def test_dedupe_id_is_stable():
    a = _dedupe_id({"US": "United States"}, "Unknown")
    b = _dedupe_id({"US": "United States"}, "Unknown")
    c = _dedupe_id({"CA": "Canada"}, "Unknown")
    assert a == b
    assert a != c
