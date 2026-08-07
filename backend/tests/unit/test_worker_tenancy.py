"""Tenant rehydration + payload/run-row cross-check (plan 046 task 4).

The queue payload's `tenant_id` is untrusted: the contextvar mechanism
`dte.tenancy` documents doesn't cross a process boundary, so the worker
must verify the claim against the run row's *actual* tenant_id (looked up
bypassing RLS) before setting `tenant_context_var` and touching any
tenant-scoped store. This is the one genuinely security-sensitive edit in
plan 046 — see plans/046-distributed-run-execution.md, "Sharp edge 2".
"""
from __future__ import annotations

import asyncio
import logging

import pytest

from dte.tenancy import tenant_context_var
from dte.worker.tasks import execute_run_job


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def stores(fake_stores):
    return fake_stores


async def _seed_pipeline(stores, pipeline_id="p1", source_id="s1", dest_id="d1"):
    from dte.models.pipeline import DestinationCreate, Pipeline, PipelineBase, SourceCreate

    await stores["source"].save(SourceCreate(
        id=source_id, connection_id="local_fs", source_type="filesystem",
        config={"bucket_url": "/tmp"}, table="dummy",
    ))
    await stores["destination"].save(DestinationCreate(
        id=dest_id, connection_id="local_fs",
        config={"type": "json_file", "path": "/tmp/wt_out.json"},
    ))
    pipeline = Pipeline(**PipelineBase(
        id=pipeline_id, name=pipeline_id, sources=[source_id],
        steps=[], output_id=dest_id,
    ).model_dump())
    await stores["pipeline"].save(pipeline)
    return pipeline


def test_tenant_match_sets_context_and_executes(stores, monkeypatch):
    """When the payload's tenant_id matches the run row's actual tenant_id,
    execution proceeds and tenant_context_var is set to that tenant for the
    duration of the call."""
    _run(_seed_pipeline(stores))
    run_id = _run(stores["run"].create("p1"))

    observed_tenant: list[str] = []

    async def fake_execute_pipeline(pipeline_id, rid, *args, **kwargs):
        observed_tenant.append(tenant_context_var.get())

    monkeypatch.setattr("dte.worker.tasks._execute_pipeline", fake_execute_pipeline)

    async def fake_lookup(rid):
        return "tenant-a"

    _run(execute_run_job(
        run_id=run_id, pipeline_id="p1", tenant_id="tenant-a",
        p_store=stores["pipeline"], r_store=stores["run"],
        re_store=stores["run_event"], s_store=stores["source"],
        d_store=stores["destination"], c_store=stores["connection"],
        lt_store=stores["lookup_table"],
        fetch_actual_tenant_id=fake_lookup,
    ))

    assert observed_tenant == ["tenant-a"]
    # Contextvar must not leak past the call.
    assert tenant_context_var.get() == "default"


def test_tenant_mismatch_fails_run_without_executing(stores, monkeypatch, caplog):
    """A payload claiming the wrong tenant must not execute the pipeline —
    the run is failed under its *real* tenant instead."""
    _run(_seed_pipeline(stores))
    run_id = _run(stores["run"].create("p1"))

    executed = False

    async def fake_execute_pipeline(*args, **kwargs):
        nonlocal executed
        executed = True

    monkeypatch.setattr("dte.worker.tasks._execute_pipeline", fake_execute_pipeline)

    async def fake_lookup(rid):
        return "tenant-real"

    with caplog.at_level(logging.ERROR, logger="dte.worker.tasks"):
        _run(execute_run_job(
            run_id=run_id, pipeline_id="p1", tenant_id="tenant-attacker",
            p_store=stores["pipeline"], r_store=stores["run"],
            re_store=stores["run_event"], s_store=stores["source"],
            d_store=stores["destination"], c_store=stores["connection"],
            lt_store=stores["lookup_table"],
            fetch_actual_tenant_id=fake_lookup,
        ))

    assert executed is False
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    run = _run(stores["run"].get(run_id))
    assert run["status"] == "failed"
    assert "tenant" in run["error"].lower()
    assert tenant_context_var.get() == "default"


def test_run_not_found_does_not_execute(stores, monkeypatch, caplog):
    """A job payload pointing at a run id that no longer resolves (e.g. a
    replayed/garbage-collected job) must not execute anything."""
    executed = False

    async def fake_execute_pipeline(*args, **kwargs):
        nonlocal executed
        executed = True

    monkeypatch.setattr("dte.worker.tasks._execute_pipeline", fake_execute_pipeline)

    async def fake_lookup(rid):
        return None

    with caplog.at_level(logging.ERROR, logger="dte.worker.tasks"):
        _run(execute_run_job(
            run_id="does-not-exist", pipeline_id="p1", tenant_id="tenant-a",
            p_store=stores["pipeline"], r_store=stores["run"],
            re_store=stores["run_event"], s_store=stores["source"],
            d_store=stores["destination"], c_store=stores["connection"],
            lt_store=stores["lookup_table"],
            fetch_actual_tenant_id=fake_lookup,
        ))

    assert executed is False
    assert any(r.levelno == logging.ERROR for r in caplog.records)
