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
        self.error = KafkaError(KafkaError.GROUP_AUTHORIZATION_FAILED)


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


class _TP:
    def __init__(self, topic, partition, offset=-1001):
        self.topic, self.partition, self.offset, self.error = topic, partition, offset, None


class _Msg:
    def __init__(self, partition, offset):
        self._p, self._o = partition, offset

    def error(self): return None
    def value(self): return b'{"id": %d}' % self._o
    def partition(self): return self._p
    def offset(self): return self._o
    def timestamp(self): return (1, 0)


class _CoordinatorMovesConsumer(_FakeConsumer):
    """`committed()` raises NOT_COORDINATOR on the first call, as a fresh
    broker does while its offsets topic loads, then answers."""
    calls = 0

    def committed(self, parts, timeout):
        type(self).calls += 1
        if type(self).calls == 1:
            raise confluent_kafka.KafkaException(KafkaError(KafkaError.NOT_COORDINATOR))
        return [_TP(parts[0].topic, 0, 8)]

    def assign(self, parts):
        self._left = [_Msg(0, o) for o in range(parts[0].offset, 10)]

    def poll(self, timeout):
        return self._left.pop(0) if self._left else None


def test_retriable_coordinator_error_is_retried(monkeypatch):
    monkeypatch.setattr(confluent_kafka, "Consumer", _CoordinatorMovesConsumer)
    monkeypatch.setattr(loader, "_KAFKA_RETRY_BASE_SECONDS", 0)
    src = Source(id="s", connection_id="k", source_type="kafka", config={"topic": "t"}, table="events")
    t = loader.load_source(src, BackendRegistry(), None, {"config": {}})
    assert sorted(t.id.to_pyarrow().to_pylist()) == [8, 9]


class _NoCommittedConsumer(_CoordinatorMovesConsumer):
    def committed(self, parts, timeout):
        raise AssertionError("a preview must not ask for committed offsets")


def test_preview_never_asks_for_committed_offsets(monkeypatch):
    monkeypatch.setattr(confluent_kafka, "Consumer", _NoCommittedConsumer)
    src = Source(id="s", connection_id="k", source_type="kafka", config={"topic": "t"}, table="events")
    t = loader.load_source(src, BackendRegistry(), None, {"config": {}}, sample=3)
    assert sorted(t.id.to_pyarrow().to_pylist()) == [7, 8, 9]
