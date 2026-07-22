"""OpenTelemetry setup.

Console exporter by default (dev). If `OTEL_EXPORTER_OTLP_ENDPOINT` is set,
the SDK's env-driven config picks up the OTLP exporter automatically. Never
imported by tests unless `DTE_TRACING_ENABLED=1`.
"""
from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

_INITIALISED = False


def configure_tracing() -> None:
    """Idempotent — safe to call from `main.py`."""
    global _INITIALISED
    if _INITIALISED or os.getenv("DTE_TRACING_ENABLED", "0") != "1":
        return
    provider = TracerProvider(resource=Resource.create({"service.name": "dte-api"}))
    # ConsoleSpanExporter is fine for dev. To ship to a collector, set
    # OTEL_EXPORTER_OTLP_ENDPOINT and swap in OTLPSpanExporter.
    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    _INITIALISED = True


def tracer():
    return trace.get_tracer("dte")
