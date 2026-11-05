"""KafkaLagTrigger against a real broker (plan 108).

    DTE_KAFKA_BOOTSTRAP=127.0.0.1:9094 uv run pytest tests/integration/test_kafka_trigger.py
"""
import asyncio
import json
import os
import uuid

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DTE_KAFKA_BOOTSTRAP"), reason="requires DTE_KAFKA_BOOTSTRAP"),
]


async def _first_event(t, timeout):
    agen = t.run()
    try:
        return await asyncio.wait_for(agen.__anext__(), timeout)
    finally:
        await agen.aclose()


async def test_fires_on_lag_and_stays_quiet_once_committed(monkeypatch):
    from confluent_kafka import Consumer, Producer, TopicPartition

    from dte.airflow.kafka_trigger import KafkaLagTrigger

    boot = os.environ["DTE_KAFKA_BOOTSTRAP"]
    monkeypatch.setenv("AIRFLOW_CONN_KAFKA_IT", json.dumps(
        {"conn_type": "kafka", "extra": {"bootstrap.servers": boot}}))
    topic, group = f"dte-trig-{uuid.uuid4().hex[:8]}", f"g-{uuid.uuid4().hex[:6]}"
    p = Producer({"bootstrap.servers": boot})
    for i in range(3):
        p.produce(topic, json.dumps({"id": i}).encode())
    assert p.flush(10) == 0

    t = KafkaLagTrigger(kafka_config_id="kafka_it", topic=topic, group_id=group, poll_interval=0.2)
    ev = await _first_event(t, timeout=30)
    assert ev.payload == {"topic": topic, "group_id": group, "lag": 3}

    # The run commits after its write; then there is nothing to fire on.
    c = Consumer({"bootstrap.servers": boot, "group.id": group})
    c.commit(offsets=[TopicPartition(topic, 0, 3)], asynchronous=False)
    c.close()
    with pytest.raises(asyncio.TimeoutError):
        await _first_event(t, timeout=2)
