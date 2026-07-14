import pytest
from tests.fakes import (
    FakePipelineStore, FakeSourceStore, FakeDestinationStore,
)
from scripts.migrate_embedded_endpoints import _migrate_pipeline


def _embedded_pipeline(pid="p1"):
    return {
        "id": pid, "name": pid,
        "sources": [
            {
                "id": "s1", "source_type": "filesystem",
                "config": {"bucket_url": "/tmp"}, "table": "t",
            }
        ],
        "steps": [],
        "output": {"type": "json_file", "path": "/tmp/out.json"},
    }


async def test_migrates_embedded_source_and_output():
    p_store = FakePipelineStore()
    s_store = FakeSourceStore()
    d_store = FakeDestinationStore()

    p = _embedded_pipeline("p1")
    log: list[str] = []
    new_p, changed = await _migrate_pipeline(p, s_store, d_store, log)

    assert changed
    assert new_p["sources"] == ["s1"]
    assert new_p["output_id"] == "p1_output"
    assert "output" not in new_p
    assert (await s_store.get("s1"))["table"] == "t"
    dest = await d_store.get("p1_output")
    assert dest["config"]["type"] == "json_file"


async def test_idempotent_when_already_id_shape():
    s_store = FakeSourceStore()
    d_store = FakeDestinationStore()
    already = {
        "id": "p1", "name": "p1", "sources": ["s1"], "steps": [], "output_id": "d1",
    }
    log: list[str] = []
    new_p, changed = await _migrate_pipeline(already, s_store, d_store, log)
    assert not changed
    assert new_p == already


async def test_id_collision_creates_suffixed_source():
    s_store = FakeSourceStore()
    d_store = FakeDestinationStore()
    # Pre-seed a different source under the same id.
    await s_store.save({
        "id": "s1", "source_type": "filesystem",
        "config": {"bucket_url": "/other"}, "table": "t",
    })
    p = _embedded_pipeline("p1")
    log: list[str] = []
    new_p, _ = await _migrate_pipeline(p, s_store, d_store, log)
    assert new_p["sources"] == ["s1-2"]
    assert any("collision" in line for line in log)


async def test_second_pipeline_gets_suffixed_destination():
    s_store = FakeSourceStore()
    d_store = FakeDestinationStore()
    # Pre-seed a destination that clashes with p1_output.
    await d_store.save({
        "id": "p1_output",
        "config": {"type": "json_file", "path": "/tmp/somewhere-else.json"},
    })
    p = _embedded_pipeline("p1")
    log: list[str] = []
    new_p, _ = await _migrate_pipeline(p, s_store, d_store, log)
    assert new_p["output_id"] == "p1_output-2"
