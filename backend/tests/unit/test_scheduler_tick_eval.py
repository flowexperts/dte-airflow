"""The ticker firing an *eval* schedule (plan 051 phase 5).

`_run_body` reads `eval_set_id` off the run row — the trigger route writes
it there via `r_store.update`. The ticker did not, so every scheduled eval
run raised "eval pipeline triggered without an eval_set_id". These tests
pin the run row, not the enqueue call, because the run row is what the
runner actually reads.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from dte.models.eval import EvalSetBase
from dte.models.pipeline import Pipeline, PipelineBase, ScheduleBase, SourceCreate


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def stores(fake_stores):
    return fake_stores


async def _seed_eval(stores):
    await stores["source"].save(SourceCreate(
        id="ev_src", connection_id="local_fs", source_type="documents",
        config={"bucket_url": "/tmp", "file_glob": "**/*.pdf"}, table="docs",
    ))
    await stores["eval_set"].save(EvalSetBase(
        id="ev_set", name="Invoices", source_id="ev_src",
        field_specs=[{"name": "total", "type": "numeric"}],
    ))
    await stores["pipeline"].save(Pipeline(**PipelineBase(
        id="ev_pipe", name="ev_pipe", sources=["ev_src"],
        steps= [
            {"op": "extract", "source_field": "path", "provider": "pdfplumber",
             "granularity": "page", "output_field": "content", "params": {}},
            {"op": "structure", "input_field": "content", "provider": "regex",
             "on_error": "null", "params": {},
             "model": {"instructions": "", "fields": [
                 {"name": "total", "type": "string", "required": False,
                  "description": "the total", "pattern": r"Total: \$([\d,.]+)"}]}},
        ], output_id=None, pipeline_type="eval",
    ).model_dump()))


def test_ticker_stamps_the_eval_set_on_the_run_row(stores, monkeypatch):
    """Without this the nightly run compiles, produces rows, and then dies
    at scoring time with no corpus — the failure plan 051 exists to catch
    would itself be the thing that fails."""
    from dte.worker import scheduler as sched_mod

    _run(_seed_eval(stores))
    now = datetime.now(UTC)
    _run(stores["schedule"].save(ScheduleBase(
        id="sch_eval", pipeline_id="ev_pipe", cron_expr="* * * * *",
        tenant_id="default", eval_set_id="ev_set",
        next_run_at=now - timedelta(seconds=5),
    )))

    async def fake_enqueue_run(pipeline_id, revision_id, *, tenant_id, schedule_id=None):
        return await stores["run"].create(pipeline_id), 1

    monkeypatch.setattr(sched_mod, "enqueue_run", fake_enqueue_run)

    _run(sched_mod.run_tick(
        sch_store=stores["schedule"], r_store=stores["run"],
        p_store=stores["pipeline"], rev_store=stores["pipeline_revision"],
        now=now,
    ))

    row = _run(stores["schedule"].get("sch_eval"))
    run = _run(stores["run"].get(row.last_run_id))
    assert run["eval_set_id"] == "ev_set"


def test_ticker_leaves_eval_set_null_for_ordinary_schedules(stores, monkeypatch):
    """`eval_set_id` must stay absent, not be written as an explicit NULL —
    'never an eval run' and 'scored nothing' have to stay distinguishable."""
    from dte.worker import scheduler as sched_mod

    _run(_seed_eval(stores))
    _run(stores["pipeline"].save(Pipeline(**PipelineBase(
        id="tx_pipe", name="tx_pipe", sources=["ev_src"], steps=[],
        output_id=None,
    ).model_dump())))
    now = datetime.now(UTC)
    _run(stores["schedule"].save(ScheduleBase(
        id="sch_tx", pipeline_id="tx_pipe", cron_expr="* * * * *",
        tenant_id="default", next_run_at=now - timedelta(seconds=5),
    )))

    async def fake_enqueue_run(pipeline_id, revision_id, *, tenant_id, schedule_id=None):
        return await stores["run"].create(pipeline_id), 1

    monkeypatch.setattr(sched_mod, "enqueue_run", fake_enqueue_run)

    _run(sched_mod.run_tick(
        sch_store=stores["schedule"], r_store=stores["run"],
        p_store=stores["pipeline"], rev_store=stores["pipeline_revision"],
        now=now,
    ))

    row = _run(stores["schedule"].get("sch_tx"))
    run = _run(stores["run"].get(row.last_run_id))
    assert run.get("eval_set_id") is None
