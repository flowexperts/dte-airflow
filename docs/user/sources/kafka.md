# Kafka

Read a Kafka topic as a source. Each run reads the messages that arrived since the last successful run, transforms them, and writes them like any other source. Schedule the pipeline every few minutes and you have micro-batch streaming.

This isn't a long-running consumer. Latency is your schedule interval plus the run time (a few seconds for 100k messages).

To try it locally, the [Docker Compose](../self-hosting/install.md) stack has a broker and [Kafka UI](https://github.com/kafbat/kafka-ui) behind a profile: `docker compose --profile kafka up -d`. Airflow reaches the broker as `kafka:9092`, your machine as `127.0.0.1:9094`, and Kafka UI is at http://localhost:8090.

## 1. Create the connection

In Airflow, **Admin → Connections**, add a connection of type `kafka`. Its extra is the Kafka client config, passed to [librdkafka](https://github.com/confluentinc/librdkafka/blob/master/CONFIGURATION.md) as is:

```json
{
  "bootstrap.servers": "broker-1:9092,broker-2:9092",
  "security.protocol": "SASL_SSL",
  "sasl.mechanisms": "PLAIN",
  "sasl.username": "dte",
  "sasl.password": "…"
}
```

Or as an environment variable:

```bash
AIRFLOW_CONN_KAFKA_ORDERS='{"conn_type": "kafka", "extra": {"bootstrap.servers": "broker-1:9092"}}'
```

Requires `apache-airflow-providers-apache-kafka` (`pip install "dte-airflow[kafka]"`; the Docker image has it).

dte sets `group.id` and `enable.auto.commit` itself, so leave them out.

## 2. Create the source

The source form doesn't offer Kafka yet. Create the source through the API or as a [pipeline file](../pipelines/in-git.md) (`sources/orders_stream.yaml`):

```yaml
id: orders_stream
name: orders_stream
connection_id: kafka_orders
source_type: kafka
table: orders
config:
  topic: orders
```

```bash
curl -X POST "$AIRFLOW/dte/api/sources" -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{
  "id": "orders_stream", "name": "orders_stream", "connection_id": "kafka_orders",
  "source_type": "kafka", "table": "orders", "config": {"topic": "orders"}
}'
```

| Config | Default | What it does |
| ------ | ------- | ------------ |
| `topic` | required | The topic to read |
| `max_messages` | `10000` | Most messages one run reads. The rest wait for the next run |
| `max_seconds` | `30` | Most time one run spends reading |
| `group_id` | `dte__<source id>` | Consumer group that holds the read position |
| `invalid_messages` | `fail` | `skip` to pass over messages that aren't JSON objects (see [Bad messages](#bad-messages)) |

## 3. Build, schedule, run

Build the pipeline as usual. Give it a [schedule](../pipelines/scheduling.md) such as every 5 minutes (`*/5 * * * *`) to keep up with the topic.

Keep **overlapping runs** off (the default). Two runs at once read the same messages.

## What each run reads

From the consumer group's position up to the newest message at the start of the run, across every partition. It stops sooner at `max_messages` or `max_seconds`; a backlog drains over several runs.

The position moves **only after the write succeeds**. A run that fails before then (a step, a [quality contract](../pipelines/types.md#quality-contracts) checked before the write, the destination) moves nothing, so the next run reads the same messages again. Nothing is lost. A contract checked *after* the write runs once the position has moved, like the write itself.

The group is stored in Kafka, so you can inspect or reset it with the usual Kafka tools. A new group starts at the oldest message the topic still keeps.

Right after a broker starts, it can answer "not coordinator" while it loads its offsets. A run retries that for about 7 seconds before failing; if it still fails, the broker isn't ready yet and the next run will work. Previews don't ask for the group's position, so they aren't affected.

## Messages and columns

Each message value must be a JSON object. Its keys become columns; nested objects become nested fields (`customer.country`, see [Field names](../pipelines/field-refs.md)). A key missing from some messages is null in those rows.

dte adds four columns to every row:

| Column | Holds |
| ------ | ----- |
| `_kafka_topic` | The topic |
| `_kafka_partition` | The partition |
| `_kafka_offset` | The message's offset in its partition |
| `_kafka_timestamp` | The message timestamp (UTC) |

Message keys and headers aren't read.

## No new messages

A run with nothing new to read is **skipped**: Airflow shows the task as skipped (no failure, no alert), the run is recorded as completed with 0 rows, and downstream pipelines that wait on this one's output aren't triggered.

## Bad messages

A value that isn't a JSON object fails the run and names it:

```
kafka orders[0]@1246: value is not a JSON object; fix or skip it (source config invalid_messages: skip)
```

The position doesn't move, so every run stops at the same message until you act. Either fix the producer and reset the group past offset 1246 of partition 0, or set `invalid_messages: skip`. With `skip`, each bad message is logged with its partition and offset and passed over. It stays in Kafka, so you can still find it.

## Duplicates

If a run writes its rows but fails to save the new position, the next run writes those rows again. That's rare (it needs Kafka to fail in the moment after the write), but possible.

To make re-reads harmless, write to PostgreSQL with **Merge** on the message's identity:

```yaml
config:
  type: postgres
  schema: public
  table: orders
  write_disposition: merge
  primary_key: [_kafka_topic, _kafka_partition, _kafka_offset]
```

Use all three columns. Offsets repeat across topics, and if two topics write to one table, a key without `_kafka_topic` makes the merge **delete the other topic's rows**. Keep the three columns in your **Select** step so they reach the destination.

With **Append**, dedupe downstream on the same three columns.

## Preview

Previews and **Infer schema** run on a sample of the **newest** messages on each partition, whatever the group's position, so a topic the pipeline has caught up on still has something to build steps on. Like other sampled sources, the sample is taken once and reused (`DTE_SAMPLE_ROWS`, default `1000`; `DTE_SAMPLE_TTL_SECONDS`, default a day). The preview says *Preview on 1,000-row sample · taken 2h ago*; **Refresh** takes a new one.

**Preview on live data** reads exactly what the next run would: from the group's position, up to `max_messages`. When the pipeline is caught up it says *no new messages since the last commit*.

No preview ever moves the position, so building and editing a pipeline doesn't affect what the next run reads. An empty topic has nothing to preview; produce a few messages first.

## Limits

- JSON values only: no Avro, Protobuf or schema registry.
- No dead-letter topic: skipped messages are only logged.
- On topics written with transactions, a run may stop at `max_seconds` instead of as soon as it has caught up.
