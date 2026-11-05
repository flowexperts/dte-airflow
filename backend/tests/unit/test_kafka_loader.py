"""Kafka loader edges that need no broker (plan 107)."""
import pytest

confluent_kafka = pytest.importorskip("confluent_kafka")

from confluent_kafka import KafkaError

from dte.engine.backend_registry import BackendRegistry
from dte.models.pipeline import Source
from dte.sources import loader


class _Meta:
    error = None
    partitions = {0: None}


class _ErroredTP:
    """What `committed()` hands back for a partition the broker could not
    answer for: `TopicPartition.error` is readonly, so a stand-in."""
    partition, offset = 0, -1001

    def __init__(self, topic):
        self.topic = topic
        self.error = KafkaError(KafkaError.UNSTABLE_OFFSET_COMMIT)


class _FakeConsumer:
    def __init__(self, conf):
        pass

    def list_topics(self, topic, timeout):
        return type("MD", (), {"topics": {topic: _Meta()}})()

    def committed(self, parts, timeout):
        # The broker answered, but not for this partition: offset stays INVALID.
        return [_ErroredTP(parts[0].topic)]

    def get_watermark_offsets(self, tp, timeout):
        return 0, 10

    def close(self):
        pass


def test_committed_offset_error_fails_instead_of_rereading(monkeypatch):
    monkeypatch.setattr(confluent_kafka, "Consumer", _FakeConsumer)
    src = Source(id="s", connection_id="k", source_type="kafka", config={"topic": "t"}, table="events")
    with pytest.raises(confluent_kafka.KafkaException):
        loader.load_source(src, BackendRegistry(), None, {"config": {}})
