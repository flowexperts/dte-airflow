"""Structured logging + request-ID context.

Uses stdlib `logging` with a tiny JSON formatter (no structlog dependency —
keeps the requirements list short). A ContextVar carries the request_id and
run_id so any log line inside a request or pipeline run gets tagged.
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

from dte.config import get_settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid
        run_id = run_id_var.get()
        if run_id:
            payload["run_id"] = run_id
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k in ("args", "msg", "levelname", "name", "exc_info", "exc_text",
                     "stack_info", "created", "msecs", "relativeCreated",
                     "levelno", "pathname", "filename", "module", "lineno",
                     "funcName", "thread", "threadName", "processName",
                     "process", "taskName"):
                continue
            if k.startswith("_"):
                continue
            payload[k] = v
        return json.dumps(payload, default=str)


class _KeyValueFormatter(logging.Formatter):
    """Dev-friendly formatter — one line, includes request/run ids when set."""

    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<5} {record.name}: {record.getMessage()}"
        rid = request_id_var.get()
        run_id = run_id_var.get()
        tags = []
        if rid:
            tags.append(f"rid={rid[:8]}")
        if run_id:
            tags.append(f"run={run_id[:8]}")
        if tags:
            base += "  [" + " ".join(tags) + "]"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging() -> None:
    """Call once at app startup. Idempotent."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if settings.log_json else _KeyValueFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())
    # Quiet noisy libs by default; the app's own loggers stay at the root level.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("s3transfer").setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
