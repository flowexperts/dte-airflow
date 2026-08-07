"""Heartbeat touching during a distributed run (plan 046 task 8)."""
from __future__ import annotations

import asyncio

import pytest


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def stores(fake_stores):
    return fake_stores


def test_heartbeat_loop_touches_run_periodically(stores):
    from dte.worker.tasks import _heartbeat_loop

    async def _go():
        run_id = await stores["run"].create("p1")
        task = asyncio.create_task(_heartbeat_loop(run_id, stores["run"], interval_seconds=0.01))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        run = await stores["run"].get(run_id)
        return run

    run = _run(_go())
    assert run["last_heartbeat_at"] is not None


def test_execute_run_job_heartbeats_while_running(stores, monkeypatch):
    """execute_run_job wraps _execute_pipeline with a heartbeat loop —
    cancelled cleanly once the pipeline finishes, and the run shows a
    heartbeat by the time execute_run_job returns."""
    from dte.worker.tasks import execute_run_job

    async def _seed():
        from dte.models.pipeline import DestinationCreate, Pipeline, PipelineBase, SourceCreate

        await stores["source"].save(SourceCreate(
            id="hb_src", connection_id="local_fs", source_type="filesystem",
            config={"bucket_url": "/tmp"}, table="dummy",
        ))
        await stores["destination"].save(DestinationCreate(
            id="hb_dst", connection_id="local_fs",
            config={"type": "json_file", "path": "/tmp/hb_out.json"},
        ))
        pipeline = Pipeline(**PipelineBase(
            id="hb_p", name="hb_p", sources=["hb_src"], steps=[], output_id="hb_dst",
        ).model_dump())
        await stores["pipeline"].save(pipeline)
        return await stores["run"].create("hb_p")

    run_id = _run(_seed())

    async def slow_execute_pipeline(pipeline_id, rid, *args, **kwargs):
        await asyncio.sleep(0.05)

    monkeypatch.setattr("dte.worker.tasks._execute_pipeline", slow_execute_pipeline)
    monkeypatch.setattr("dte.worker.tasks.HEARTBEAT_INTERVAL_SECONDS", 0.01)

    async def fake_lookup(rid):
        return "default"

    _run(execute_run_job(
        run_id=run_id, pipeline_id="hb_p", tenant_id="default",
        p_store=stores["pipeline"], r_store=stores["run"],
        re_store=stores["run_event"], s_store=stores["source"],
        d_store=stores["destination"], c_store=stores["connection"],
        lt_store=stores["lookup_table"],
        fetch_actual_tenant_id=fake_lookup,
    ))

    run = _run(stores["run"].get(run_id))
    assert run["last_heartbeat_at"] is not None
