"""KafkaLagTrigger (plan 108): fires on the pipeline group's lag, nothing else."""
import asyncio

import pytest

pytest.importorskip("confluent_kafka")
pytest.importorskip("airflow")

from dte.airflow.kafka_trigger import KafkaLagTrigger


def _trigger(lags, monkeypatch):
    t = KafkaLagTrigger(kafka_config_id="k", topic="orders", group_id="g", poll_interval=0)
    seq = iter(lags)
    monkeypatch.setattr(t, "_lag", lambda: next(seq))
    return t


async def _first_event(t, timeout=0.5):
    agen = t.run()
    try:
        return await asyncio.wait_for(agen.__anext__(), timeout)
    finally:
        await agen.aclose()


async def test_fires_once_the_group_has_lag(monkeypatch):
    ev = await _first_event(_trigger([0, 0, 3], monkeypatch))
    assert ev.payload == {"topic": "orders", "group_id": "g", "lag": 3}


async def test_quiet_while_caught_up(monkeypatch):
    t = _trigger(iter(lambda: 0, 1), monkeypatch)  # lag 0 forever
    with pytest.raises(asyncio.TimeoutError):
        await _first_event(t, timeout=0.2)


async def test_sleeps_before_the_first_check(monkeypatch):
    """A re-armed trigger must not fire on the lag of the run it just started."""
    calls = []
    t = KafkaLagTrigger(kafka_config_id="k", topic="orders", group_id="g", poll_interval=0.3)
    monkeypatch.setattr(t, "_lag", lambda: calls.append(1) or 1)
    with pytest.raises(asyncio.TimeoutError):
        await _first_event(t, timeout=0.1)
    assert calls == []


def test_serialize_round_trips():
    t = KafkaLagTrigger(kafka_config_id="k", topic="orders", group_id="g")
    path, kwargs = t.serialize()
    assert path == "dte.airflow.kafka_trigger.KafkaLagTrigger"
    assert KafkaLagTrigger(**kwargs).serialize() == (path, kwargs)
