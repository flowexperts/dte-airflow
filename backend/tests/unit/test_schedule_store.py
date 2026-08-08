"""FakeScheduleStore behaviour (plan 047 task 2) — list_due / advance
semantics the ticker (task 5) depends on."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from dte.models.pipeline import ScheduleBase


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def store(fake_stores):
    return fake_stores["schedule"]


def _sched(**overrides) -> ScheduleBase:
    base = {"id": "sch_1", "pipeline_id": "p1", "cron_expr": "0 2 * * *"}
    base.update(overrides)
    return ScheduleBase(**base)


def test_save_and_get_round_trip(store):
    _run(store.save(_sched()))
    got = _run(store.get("sch_1"))
    assert got is not None
    assert got.pipeline_id == "p1"
    assert got.enabled is True


def test_list_for_pipeline_filters(store):
    _run(store.save(_sched(id="a", pipeline_id="p1")))
    _run(store.save(_sched(id="b", pipeline_id="p2")))
    result = _run(store.list_for_pipeline("p1"))
    assert [s.id for s in result] == ["a"]


def test_list_due_excludes_disabled(store):
    now = datetime.now(UTC)
    _run(store.save(_sched(id="due", next_run_at=now - timedelta(minutes=1))))
    _run(store.save(_sched(id="disabled", enabled=False, next_run_at=now - timedelta(minutes=1))))
    result = _run(store.list_due(now))
    assert [s.id for s in result] == ["due"]


def test_list_due_excludes_null_next_run_at(store):
    now = datetime.now(UTC)
    _run(store.save(_sched(id="no-next-run", next_run_at=None)))
    result = _run(store.list_due(now))
    assert result == []


def test_list_due_excludes_future(store):
    now = datetime.now(UTC)
    _run(store.save(_sched(id="future", next_run_at=now + timedelta(hours=1))))
    result = _run(store.list_due(now))
    assert result == []


def test_advance_updates_next_run_at_only_on_skip(store):
    now = datetime.now(UTC)
    _run(store.save(_sched(id="s1", next_run_at=now)))
    later = now + timedelta(minutes=1)
    _run(store.advance("s1", next_run_at=later))
    row = _run(store.get("s1"))
    assert row.next_run_at == later
    assert row.last_run_id is None


def test_advance_sets_last_run_id_and_fired_at_on_fire(store):
    now = datetime.now(UTC)
    _run(store.save(_sched(id="s1", next_run_at=now)))
    later = now + timedelta(minutes=1)
    _run(store.advance("s1", next_run_at=later, last_run_id="run_123", last_fired_at=now))
    row = _run(store.get("s1"))
    assert row.next_run_at == later
    assert row.last_run_id == "run_123"
    assert row.last_fired_at == now


def test_delete(store):
    _run(store.save(_sched()))
    assert _run(store.delete("sch_1")) is True
    assert _run(store.get("sch_1")) is None
    assert _run(store.delete("sch_1")) is False
