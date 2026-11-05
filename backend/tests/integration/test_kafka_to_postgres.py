"""Kafka source → Postgres destination (plan 107).

Needs a broker and a Postgres:

    docker run -d --name dte-it-kafka -p 127.0.0.1:59092:9092 ... apache/kafka
    DTE_KAFKA_BOOTSTRAP=127.0.0.1:59092 DTE_DATABASE_URL=... uv run pytest tests/integration/test_kafka_to_postgres.py
"""
import json
import os
import uuid
from urllib.parse import urlparse

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not (os.getenv("DTE_DATABASE_URL") and os.getenv("DTE_KAFKA_BOOTSTRAP")),
                       reason="requires DTE_DATABASE_URL and DTE_KAFKA_BOOTSTRAP"),
]

import ibis

from dte.airflow.runner import run_pipeline
from dte.models.pipeline import Connection, Destination, Pipeline, Source, SourceTableRef


def _pg_url() -> str:
    return os.environ["DTE_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")


def _pg():
    u = urlparse(_pg_url())
    return ibis.postgres.connect(host=u.hostname, port=u.port, user=u.username,
                                 password=u.password, database=u.path.lstrip("/"))


def _produce(topic: str, rows: list[dict]) -> None:
    from confluent_kafka import Producer

    p = Producer({"bootstrap.servers": os.environ["DTE_KAFKA_BOOTSTRAP"]})
    for r in rows:
        p.produce(topic, json.dumps(r).encode())
    assert p.flush(10) == 0


@pytest.fixture
def pg_table():
    name = f"t107_{uuid.uuid4().hex[:8]}"
    yield name
    _pg().raw_sql(f'DROP TABLE IF EXISTS public."{name}"')


def test_kafka_to_postgres_commits_only_after_write(pg_table):
    topic = f"dte-it-{uuid.uuid4().hex[:8]}"
    _produce(topic, [{"id": 1, "amount": 10}, {"id": 2, "amount": 20}, {"id": 3, "amount": 30}])

    conn = Connection(id="kafka", connection_type="kafka",
                      credentials={"config": {"bootstrap.servers": os.environ["DTE_KAFKA_BOOTSTRAP"]}})
    src = Source(id=f"s_{topic}", connection_id="kafka", source_type="kafka",
                 config={"topic": topic, "max_seconds": 10}, table="events")
    ref = SourceTableRef(source_id=src.id, alias="events")
    dest = Destination(id="d", connection_id="pg", dest_type="postgres",
                       config={"type": "postgres", "schema": "public", "table": pg_table,
                               "write_disposition": "append"})
    dest.narrow_config()
    p = Pipeline(id="p", name="p", sources=[ref.model_dump()],
                 steps=[{"op": "filter", "expr": "amount > 10"}], output_id="d")

    def run(dest_creds):
        return run_pipeline(p, [(ref, src, conn, conn.credentials)], (dest, dest_creds))

    # A failed write commits nothing ...
    with pytest.raises(ValueError):
        run({})
    # ... so the next run re-reads the same slice.
    assert run({"url": _pg_url()}).rows_written == 2

    # Only messages produced since the last commit are read.
    _produce(topic, [{"id": 4, "amount": 40}, {"id": 5, "amount": 5}])
    assert run({"url": _pg_url()}).rows_written == 1

    ids = _pg().table(pg_table, database="public").id.to_pyarrow().to_pylist()
    assert sorted(ids) == [2, 3, 4]


def _conn() -> Connection:
    return Connection(id="kafka", connection_type="kafka",
                      credentials={"config": {"bootstrap.servers": os.environ["DTE_KAFKA_BOOTSTRAP"]}})


def _setup(pg_table, topic, steps=(), dest_extra=None, **cfg):
    conn = _conn()
    src = Source(id=f"s_{topic}", connection_id="kafka", source_type="kafka",
                 config={"topic": topic, "max_seconds": 10, **cfg}, table="events")
    ref = SourceTableRef(source_id=src.id, alias="events")
    dest = Destination(id="d", connection_id="pg", dest_type="postgres",
                       config={"type": "postgres", "schema": "public", "table": pg_table,
                               "write_disposition": "append", **(dest_extra or {})})
    dest.narrow_config()
    p = Pipeline(id="p", name="p", sources=[ref.model_dump()], steps=list(steps), output_id="d")
    return lambda: run_pipeline(p, [(ref, src, conn, conn.credentials)], (dest, {"url": _pg_url()}))


def _ids(pg_table):
    return sorted(_pg().table(pg_table, database="public").id.to_pyarrow().to_pylist())


def test_idle_run_is_skipped_not_failed(pg_table):
    topic = f"dte-it-{uuid.uuid4().hex[:8]}"
    _produce(topic, [{"id": 1, "amount": 10}])
    run = _setup(pg_table, topic, steps=[{"op": "filter", "expr": "amount > 0"}])
    assert run().rows_written == 1

    res = run()  # nothing new: the filter's `amount` must not be looked up
    assert res.status == "completed" and res.rows_written == 0
    assert "no new messages" in res.skip_reason


def test_invalid_message_names_its_offset_and_commits_nothing(pg_table):
    from confluent_kafka import Producer

    topic = f"dte-it-{uuid.uuid4().hex[:8]}"
    _produce(topic, [{"id": 1}])
    p = Producer({"bootstrap.servers": os.environ["DTE_KAFKA_BOOTSTRAP"]})
    p.produce(topic, b"not json {")
    p.flush(10)
    _produce(topic, [{"id": 3}])

    with pytest.raises(ValueError, match=rf"{topic}\[0\]@1"):
        _setup(pg_table, topic)()
    # Opt in to skipping: the bad offset is passed over, everything else lands.
    assert _setup(pg_table, topic, invalid_messages="skip")().rows_written == 2
    assert _ids(pg_table) == [1, 3]


def test_merge_key_makes_a_replayed_slice_idempotent(pg_table):
    from confluent_kafka import Consumer, TopicPartition

    key = {"write_disposition": "merge", "primary_key": ["_kafka_topic", "_kafka_partition", "_kafka_offset"]}
    # A second topic in the same table: its offsets overlap the first's, and a
    # key without the topic would let the replay below delete its rows.
    other = f"dte-it-{uuid.uuid4().hex[:8]}"
    _produce(other, [{"id": 10}, {"id": 20}])
    assert _setup(pg_table, other, dest_extra=key)().rows_written == 2

    topic = f"dte-it-{uuid.uuid4().hex[:8]}"
    _produce(topic, [{"id": 1}, {"id": 2}])
    run = _setup(pg_table, topic, dest_extra=key)
    assert run().rows_written == 2

    # The write landed but the commit was lost: rewind the group and run again.
    c = Consumer({"bootstrap.servers": os.environ["DTE_KAFKA_BOOTSTRAP"], "group.id": f"dte__s_{topic}"})
    c.commit(offsets=[TopicPartition(topic, 0, 0)], asynchronous=False)
    c.close()
    assert run().rows_written == 2
    assert _ids(pg_table) == [1, 2, 10, 20]


def test_preview_reads_the_newest_messages_even_when_caught_up(pg_table):
    from dte.engine.backend_registry import BackendRegistry
    from dte.sources.loader import load_source

    topic = f"dte-it-{uuid.uuid4().hex[:8]}"
    _produce(topic, [{"id": i} for i in range(5)])
    assert _setup(pg_table, topic)().rows_written == 5  # group is caught up

    src = Source(id=f"s_{topic}", connection_id="kafka", source_type="kafka",
                 config={"topic": topic, "max_seconds": 10}, table="events")
    reg = BackendRegistry()
    t = load_source(src, reg, _conn(), _conn().credentials, sample=2)
    assert sorted(t.id.to_pyarrow().to_pylist()) == [3, 4]
    assert reg.after_write == []
