"""Prometheus metric registry (P3 #30).

Module-level singletons — Prometheus complains if a metric is registered
twice, so imports must be idempotent. See ``plans/031-observability-slo-metrics-oncall.md``.

HTTP RED metrics are handled by ``prometheus-fastapi-instrumentator`` in
``dte.api.main``. This module owns the domain metrics.
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# Histogram buckets tuned for pipeline runs: sub-second preview through
# hour-long batch. Same buckets are reused for source-load durations
# so dashboards can subtract to isolate compile+write time.
_DURATION_BUCKETS = (0.5, 1, 2, 5, 10, 30, 60, 300, 900, 3600)

pipeline_runs_total = Counter(
    "dte_pipeline_runs_total",
    "Terminal pipeline runs by status",
    labelnames=("status",),
)

pipeline_run_duration_seconds = Histogram(
    "dte_pipeline_run_duration_seconds",
    "End-to-end pipeline run duration",
    labelnames=("source_type",),
    buckets=_DURATION_BUCKETS,
)

source_load_duration_seconds = Histogram(
    "dte_source_load_duration_seconds",
    "Time spent materialising a source into an ibis.Table",
    labelnames=("source_type",),
    buckets=_DURATION_BUCKETS,
)

rows_written_total = Counter(
    "dte_rows_written_total",
    "Rows written by destination type",
    labelnames=("destination_type",),
)

compile_duration_seconds = Histogram(
    "dte_compile_duration_seconds",
    "Time spent in compile_pipeline (before execution)",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5),
)

active_runs = Gauge(
    "dte_active_runs",
    "Runs currently in pending/running state",
)
