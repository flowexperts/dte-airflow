# 108 — Run on new Kafka messages (event-driven schedule)

Follows plan 107 (Kafka source).

## Problem

A Kafka pipeline runs on a cron or by hand. A stream wants it always on:
run when messages arrive, not every minute whether or not they did.

## Findings (spike against the installed Airflow 3.3.2)

- **Airflow's `MessageQueueTrigger(scheme="kafka")` is the wrong shape.** It
  wraps `AwaitMessageTrigger`, which *consumes* the topic with its own
  consumer group, fires once per matching message, then ends and is re-armed
  with a fresh consumer. At 5 msg/s that is an event and a group join per
  message, and a second group that permanently lags DTE's.
- **Bursts collapse.** `DagModel.dags_needing_dagruns` defers an
  asset-triggered DAG that is at `max_active_runs`, leaving its one
  `AssetDagRunQueue` row (one per asset/DAG). Events during a run become one
  follow-up run, not one per event.

## Design

`schedule.mode = "messages"`: the DAG runs when any of the pipeline's Kafka
sources has unread messages.

- **`KafkaLagTrigger`** (`dte/airflow/kafka_trigger.py`, a `BaseEventTrigger`)
  watches the *pipeline's own* consumer group: committed offsets vs high
  watermarks, every `poll_interval` seconds (default 5). Lag > 0 → one
  `TriggerEvent`, then the trigger ends and Airflow re-arms it. It never
  reads a message, commits, or joins the group, so DTE's commit-after-write
  stays the single source of truth.
- **It sleeps before checking**, including the first check after a re-arm.
  Without that, a re-armed trigger sees the lag of the run it just started
  and fires in a tight loop. With it: at most one event per interval, and
  those collapse into one queued run (above).
- **DAG factory:** one `Asset(dte://<conn>/kafka/<topic>)` per Kafka source,
  with an `AssetWatcher` running the trigger; `schedule` = any of them. The
  same URI is the task's inlet, so lineage shows the topic.
- **Validation:** `messages` needs at least one Kafka source, and refuses
  `overlap: allow` (two runs would read the same slice).
- **Compose** gets an `airflow-triggerer` service. Watchers run there; the
  stack had none.

Cost: an AssetEvent row per fire (at most one per interval while data
flows), cleaned by `airflow db clean`. Latency: the interval plus run start.

## Not in scope

File-mode DAGs (no source rows at parse time, like `assets` mode today),
non-Kafka event sources, per-topic intervals in the UI.

## Tasks — branch `feature/108-kafka-event-schedule`

1. Failing tests: schedule validation, DAG factory watcher, trigger logic
   (fake consumer), trigger against a real broker.
2. `PipelineSchedule.mode` + `validate_schedule` (needs the source store).
3. `KafkaLagTrigger` (reuses `loader._kafka_committed`).
4. DAG factory + `asset_uri` for Kafka.
5. Compose triggerer; form option; API types.
6. Docs: Kafka guide, scheduling, release notes. End-to-end in Docker.

## Files

- `backend/dte/models/pipeline.py`, `backend/dte/api/routes/schedules.py`,
  `backend/dte/api/routes/pipelines.py`
- `backend/dte/airflow/kafka_trigger.py` (new), `dag_factory.py`, `assets.py`
- `docker-compose.yml`
- `frontend/src/components/builder/schedules/{ScheduleForm,SchedulePanel}.tsx`,
  `frontend/src/lib/api.ts`, `frontend/src/lib/api-types.ts`
- `docs/user/sources/kafka.md`, `docs/user/pipelines/scheduling.md`,
  `docs/user/releases.md`
- tests: `tests/unit/test_api_pipeline_schedule.py`,
  `tests/airflow/test_dag_factory.py`, `tests/unit/test_kafka_trigger.py`,
  `tests/integration/test_kafka_to_postgres.py`
