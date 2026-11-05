# 107 — Kafka as a source (bounded micro-batch)

Roadmap #38 (plan 035), MVP only.

## Problem

DTE has no streaming source. Testing Kafka → Postgres needs a `kafka`
source kind; the Postgres destination already exists.

## Design

Every run reads a **bounded slice**, then transforms and writes as usual:
up to `max_messages`, or `max_seconds`, or until the topic has nothing new.

- **Offsets live in Kafka.** Consumer group `config.group_id` (default
  `dte__<source id>`), `enable.auto.commit=false`. No DTE offset table.
- **Commit after the write, never before.** The loader reads, closes its
  consumer and registers a commit on `BackendRegistry.after_write`; the
  runner calls those only after `engine.execute` succeeds. A failed run
  commits nothing, so the next run re-reads the slice: at-least-once.
  The commit uses a fresh consumer with explicit offsets, which Kafka
  allows once the group is empty, so preview/quality/eval paths (which
  never call `after_write`) leak no consumer.
- **Values are JSON objects.** A row per message, plus `_kafka_partition`,
  `_kafka_offset`, `_kafka_timestamp`. A non-JSON value fails the load
  (nothing committed) instead of dropping the message.
- **Connection** is an Airflow `kafka` connection
  (`apache-airflow-providers-apache-kafka`, in Airflow's constraints). Its
  extra is the librdkafka config dict (`bootstrap.servers`, SASL, …).
- Kafka is `EAGER`: interactive paths get the sampled, cached parquet.

## Follow-up fixes (from the end-to-end test report)

1. **Idle runs failed** (no data columns). Loader raises `NoNewMessages`;
   the runner returns `completed`, 0 rows, `skip_reason`; the operator
   raises `AirflowSkipException`.
2. **A non-JSON message blocked the topic** with a bare `JSONDecodeError`.
   The error now names `topic[partition]@offset`; `invalid_messages: skip`
   logs it and moves on (the message stays in Kafka).
3. **Replays duplicated rows.** `PostgresTarget.primary_key` (merge only)
   feeds dlt's upsert. Key: `_kafka_topic, _kafka_partition, _kafka_offset`
   — the test caught that a key without the topic deletes another topic's
   rows in a shared table, so `_kafka_topic` is now a column.
4. **A `committed()` per-partition error read as "no commit"** (replay from
   earliest). It now fails the load.

Previews read each partition's newest messages, so a caught-up topic can
still be previewed.

## Not in scope

Long-lived consumers, CDC, Avro/schema registry, dead-letter topics, a
Kafka form in the UI.

## Tasks — branch `feature/107-kafka-source`

1. Failing integration test: produce to Kafka, run, rows land in Postgres,
   second run reads nothing new, a failed write commits nothing.
2. `kafka` in `ConnectionType`, `SourceKind`, `KafkaSourceConfig`, compat
   maps, `ENGINE_READ_SUPPORT["duckdb"]`, `from_airflow`/`KINDS`.
3. `_load_kafka` + `BackendRegistry.after_write` + runner hook.
4. `kafka` extra in `pyproject.toml`; installed in `Dockerfile.airflow`.

## Files

- `backend/dte/models/pipeline.py`
- `backend/dte/sources/loader.py`
- `backend/dte/engine/backend_registry.py`
- `backend/dte/airflow/runner.py`, `backend/dte/airflow/connections.py`
- `backend/pyproject.toml`, `Dockerfile.airflow`
- `backend/tests/integration/test_kafka_to_postgres.py`
