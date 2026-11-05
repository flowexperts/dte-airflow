"""Fire a pipeline when its Kafka consumer group has lag (plan 108).

Airflow's own Kafka trigger (`MessageQueueTrigger(scheme="kafka")`) consumes
the topic with a second consumer group and fires once per message. This one
reads nothing: it compares the pipeline's own group's committed offsets with
the topic's high watermarks, so the run's commit-after-write stays the only
record of what has been processed.

An `AssetWatcher` runs it in the triggerer. Each event ends the trigger and
Airflow re-arms it; events that land while a run is in progress collapse into
one queued run (the DAG is at `max_active_runs=1`).
"""
from __future__ import annotations

import asyncio
from typing import Any

from airflow.triggers.base import BaseEventTrigger, TriggerEvent


class KafkaLagTrigger(BaseEventTrigger):
    def __init__(self, kafka_config_id: str, topic: str, group_id: str, poll_interval: float = 5.0) -> None:
        super().__init__()
        self.kafka_config_id = kafka_config_id
        self.topic = topic
        self.group_id = group_id
        self.poll_interval = float(poll_interval)

    def serialize(self) -> tuple[str, dict[str, Any]]:
        return ("dte.airflow.kafka_trigger.KafkaLagTrigger",
                {"kafka_config_id": self.kafka_config_id, "topic": self.topic,
                 "group_id": self.group_id, "poll_interval": self.poll_interval})

    def _lag(self) -> int:
        """Unread messages for the group across the topic's partitions."""
        from confluent_kafka import Consumer, TopicPartition

        from dte.airflow.connections import to_dte
        from dte.sources.loader import _kafka_committed

        _, creds = to_dte(self.kafka_config_id)
        # No subscribe/assign: committed() and watermarks never join the group.
        c = Consumer({**(creds.get("config") or {}), "group.id": self.group_id, "enable.auto.commit": False})
        try:
            parts = [TopicPartition(self.topic, p)
                     for p in c.list_topics(self.topic, timeout=10).topics[self.topic].partitions]
            lag = 0
            for tp in _kafka_committed(c, parts):
                lo, hi = c.get_watermark_offsets(tp, timeout=10)
                lag += hi - max(tp.offset, lo)
            return lag
        finally:
            c.close()

    async def run(self):
        while True:
            # Sleep first: a re-armed trigger would otherwise fire at once on
            # the lag of the run its last event just started.
            await asyncio.sleep(self.poll_interval)
            lag = await asyncio.to_thread(self._lag)
            if lag > 0:
                yield TriggerEvent({"topic": self.topic, "group_id": self.group_id, "lag": lag})
                return
