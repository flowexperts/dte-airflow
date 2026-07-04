import pytest
from dte.store.memory import MemoryPipelineStore, MemoryRunStore


async def test_pipeline_save_and_get():
    store = MemoryPipelineStore()
    pipeline = {"id": "p1", "name": "test"}
    await store.save(pipeline)
    result = await store.get("p1")
    assert result == pipeline


async def test_pipeline_get_missing_returns_none():
    store = MemoryPipelineStore()
    result = await store.get("nonexistent")
    assert result is None


async def test_pipeline_list_pagination():
    store = MemoryPipelineStore()
    for i in range(5):
        await store.save({"id": f"p{i}", "name": f"pipeline {i}"})
    page1 = await store.list(limit=3, offset=0)
    assert len(page1) == 3
    page2 = await store.list(limit=3, offset=3)
    assert len(page2) == 2


async def test_pipeline_delete():
    store = MemoryPipelineStore()
    await store.save({"id": "p1", "name": "test"})
    deleted = await store.delete("p1")
    assert deleted is True
    result = await store.get("p1")
    assert result is None


async def test_pipeline_delete_missing_returns_false():
    store = MemoryPipelineStore()
    result = await store.delete("nonexistent")
    assert result is False


async def test_run_create_returns_id():
    store = MemoryRunStore()
    run_id = await store.create("p1")
    assert isinstance(run_id, str)
    assert len(run_id) > 0


async def test_run_update_status():
    store = MemoryRunStore()
    run_id = await store.create("p1")
    await store.update(run_id, status="running")
    run = await store.get(run_id)
    assert run["status"] == "running"


async def test_run_list_for_pipeline():
    store = MemoryRunStore()
    run_id = await store.create("p1")
    runs = await store.list_for_pipeline("p1")
    assert len(runs) == 1
    assert runs[0]["id"] == run_id


async def test_run_list_only_returns_own_pipeline_runs():
    store = MemoryRunStore()
    await store.create("p1")
    await store.create("p1")
    await store.create("p2")
    p1_runs = await store.list_for_pipeline("p1")
    assert len(p1_runs) == 2
    p2_runs = await store.list_for_pipeline("p2")
    assert len(p2_runs) == 1
