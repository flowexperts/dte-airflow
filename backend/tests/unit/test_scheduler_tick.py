"""The schedule ticker (plan 047 task 5) — `run_tick`, the single
code-defined periodic task's body. Registered as `@app.periodic` in
`dte.worker.app` (procrastinate dedups so only one worker fires a given
minute across the whole pool); tested here as a plain async function so
none of that machinery needs to be live.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from dte.models.pipeline import (
    DestinationCreate,
    Pipeline,
    PipelineBase,
    ScheduleBase,
    SourceCreate,
)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def stores(fake_stores):
    return fake_stores


async def _seed_pipeline(stores, pid="tick_p", source_id="tick_src", dest_id="tick_dst", params=None):
    await stores["source"].save(SourceCreate(
        id=source_id, connection_id="local_fs", source_type="filesystem",
        config={"bucket_url": "/tmp"}, table="dummy",
    ))
    await stores["destination"].save(DestinationCreate(
        id=dest_id, connection_id="local_fs",
        config={"type": "json_file", "path": "/tmp/tick_out.json"},
    ))
    pipeline = Pipeline(**PipelineBase(
        id=pid, name=pid, sources=[source_id], steps=[], output_id=dest_id,
        params=params or [],
    ).model_dump())
    await stores["pipeline"].save(pipeline)
    return pid


def _sched(**overrides) -> ScheduleBase:
    base = {
        "id": "sch_tick", "pipeline_id": "tick_p", "cron_expr": "* * * * *",
        "tenant_id": "default",
    }
    base.update(overrides)
    return ScheduleBase(**base)


def test_tick_fires_due_schedule_and_advances(stores, monkeypatch):
    from dte.worker import scheduler as sched_mod

    _run(_seed_pipeline(stores))
    now = datetime.now(UTC)
    _run(stores["schedule"].save(_sched(next_run_at=now - timedelta(seconds=5))))

    enqueue_calls = []

    async def fake_enqueue_run(pipeline_id, revision_id, *, tenant_id, schedule_id=None):
        enqueue_calls.append((pipeline_id, revision_id, tenant_id, schedule_id))
        return "run_fired", 1

    monkeypatch.setattr(sched_mod, "enqueue_run", fake_enqueue_run)

    _run(sched_mod.run_tick(
        sch_store=stores["schedule"], r_store=stores["run"],
        p_store=stores["pipeline"], rev_store=stores["pipeline_revision"],
        now=now,
    ))

    assert len(enqueue_calls) == 1
    assert enqueue_calls[0][0] == "tick_p"
    assert enqueue_calls[0][2] == "default"
    assert enqueue_calls[0][3] == "sch_tick"

    row = _run(stores["schedule"].get("sch_tick"))
    assert row.last_run_id == "run_fired"
    assert row.last_fired_at == now
    assert row.next_run_at > now


def test_tick_ignores_not_yet_due_schedule(stores, monkeypatch):
    from dte.worker import scheduler as sched_mod

    _run(_seed_pipeline(stores))
    now = datetime.now(UTC)
    _run(stores["schedule"].save(_sched(next_run_at=now + timedelta(hours=1))))

    enqueue_calls = []

    async def fake_enqueue_run(*a, **kw):
        enqueue_calls.append((a, kw))
        return "run_x", 1

    monkeypatch.setattr(sched_mod, "enqueue_run", fake_enqueue_run)

    _run(sched_mod.run_tick(
        sch_store=stores["schedule"], r_store=stores["run"],
        p_store=stores["pipeline"], rev_store=stores["pipeline_revision"],
        now=now,
    ))

    assert enqueue_calls == []


def test_tick_skips_stale_beyond_grace_period(stores, monkeypatch):
    from dte.worker import scheduler as sched_mod

    _run(_seed_pipeline(stores))
    now = datetime.now(UTC)
    stale_next_run_at = now - timedelta(seconds=sched_mod.GRACE_SECONDS_DEFAULT + 60)
    _run(stores["schedule"].save(_sched(next_run_at=stale_next_run_at)))

    enqueue_calls = []

    async def fake_enqueue_run(*a, **kw):
        enqueue_calls.append((a, kw))
        return "run_x", 1

    monkeypatch.setattr(sched_mod, "enqueue_run", fake_enqueue_run)

    _run(sched_mod.run_tick(
        sch_store=stores["schedule"], r_store=stores["run"],
        p_store=stores["pipeline"], rev_store=stores["pipeline_revision"],
        now=now,
    ))

    assert enqueue_calls == []
    row = _run(stores["schedule"].get("sch_tick"))
    # Still advanced past the stale time, so it doesn't get stuck retrying
    # the same stale tick forever.
    assert row.next_run_at > now
    assert row.last_run_id is None


def test_tick_skips_overlap_when_previous_run_still_in_flight(stores, monkeypatch):
    from dte.worker import scheduler as sched_mod

    _run(_seed_pipeline(stores))
    now = datetime.now(UTC)
    prior_run_id = _run(stores["run"].create("tick_p"))
    _run(stores["run"].update(prior_run_id, status="running"))
    _run(stores["schedule"].save(_sched(
        next_run_at=now - timedelta(seconds=5),
        overlap="skip", last_run_id=prior_run_id,
    )))

    enqueue_calls = []

    async def fake_enqueue_run(*a, **kw):
        enqueue_calls.append((a, kw))
        return "run_x", 1

    monkeypatch.setattr(sched_mod, "enqueue_run", fake_enqueue_run)

    _run(sched_mod.run_tick(
        sch_store=stores["schedule"], r_store=stores["run"],
        p_store=stores["pipeline"], rev_store=stores["pipeline_revision"],
        now=now,
    ))

    assert enqueue_calls == []
    row = _run(stores["schedule"].get("sch_tick"))
    assert row.next_run_at > now
    # last_run_id untouched — still points at the in-flight run.
    assert row.last_run_id == prior_run_id


def test_tick_fires_with_overlap_allow_even_if_previous_running(stores, monkeypatch):
    from dte.worker import scheduler as sched_mod

    _run(_seed_pipeline(stores))
    now = datetime.now(UTC)
    prior_run_id = _run(stores["run"].create("tick_p"))
    _run(stores["run"].update(prior_run_id, status="running"))
    _run(stores["schedule"].save(_sched(
        next_run_at=now - timedelta(seconds=5),
        overlap="allow", last_run_id=prior_run_id,
    )))

    async def fake_enqueue_run(pipeline_id, revision_id, *, tenant_id, schedule_id=None):
        return "run_new", 1

    monkeypatch.setattr(sched_mod, "enqueue_run", fake_enqueue_run)

    _run(sched_mod.run_tick(
        sch_store=stores["schedule"], r_store=stores["run"],
        p_store=stores["pipeline"], rev_store=stores["pipeline_revision"],
        now=now,
    ))

    row = _run(stores["schedule"].get("sch_tick"))
    assert row.last_run_id == "run_new"


def test_tick_resolves_params_and_persists_run_context(stores, monkeypatch):
    from dte.worker import scheduler as sched_mod

    _run(_seed_pipeline(stores, params=[
        {"name": "region", "type": "string", "required": False, "default": "us"},
    ]))
    now = datetime.now(UTC)
    _run(stores["schedule"].save(_sched(
        next_run_at=now - timedelta(seconds=5), params={"region": "eu"},
    )))

    async def fake_enqueue_run(pipeline_id, revision_id, *, tenant_id, schedule_id=None):
        run_id = await stores["run"].create(pipeline_id)
        return run_id, 1

    monkeypatch.setattr(sched_mod, "enqueue_run", fake_enqueue_run)

    _run(sched_mod.run_tick(
        sch_store=stores["schedule"], r_store=stores["run"],
        p_store=stores["pipeline"], rev_store=stores["pipeline_revision"],
        now=now,
    ))

    row = _run(stores["schedule"].get("sch_tick"))
    run = _run(stores["run"].get(row.last_run_id))
    # run_context shape from resolve_context(): {"params": {...}, "now": ..., ...}.
    assert run["params"]["params"]["region"] == "eu"
    assert "now" in run["params"]


def test_tick_one_bad_schedule_does_not_block_others(stores, monkeypatch, caplog):
    import logging

    from dte.worker import scheduler as sched_mod

    _run(_seed_pipeline(stores, pid="tick_p", source_id="tick_src", dest_id="tick_dst"))
    now = datetime.now(UTC)
    # Bad schedule: points at a pipeline that no longer exists.
    _run(stores["schedule"].save(_sched(
        id="sch_bad", pipeline_id="does-not-exist",
        next_run_at=now - timedelta(seconds=5),
    )))
    _run(stores["schedule"].save(_sched(
        id="sch_good", pipeline_id="tick_p",
        next_run_at=now - timedelta(seconds=5),
    )))

    async def fake_enqueue_run(pipeline_id, revision_id, *, tenant_id, schedule_id=None):
        return f"run_{schedule_id}", 1

    monkeypatch.setattr(sched_mod, "enqueue_run", fake_enqueue_run)

    with caplog.at_level(logging.ERROR, logger="dte.worker.scheduler"):
        _run(sched_mod.run_tick(
            sch_store=stores["schedule"], r_store=stores["run"],
            p_store=stores["pipeline"], rev_store=stores["pipeline_revision"],
            now=now,
        ))

    good = _run(stores["schedule"].get("sch_good"))
    assert good.last_run_id == "run_sch_good"
    assert any(r.levelno == logging.ERROR for r in caplog.records)
