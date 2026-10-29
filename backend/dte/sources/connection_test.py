"""Connectivity probe for a Connection (plan 074).

The provider owns the test, as it owns the auth: this calls the Airflow
connection's own `test_connection()`, which delegates to the provider hook.
Airflow's `[core] test_connection` switch (off by default, because testing
lets a caller make the server reach arbitrary hosts) is honoured.
"""
from __future__ import annotations

import time

from dte.models.pipeline import Connection


class ProbeResult(dict):
    """`{ok: bool, elapsed_ms: int, detail: str}`."""


def _result(ok: bool, t0: float, detail: str) -> ProbeResult:
    return ProbeResult(ok=ok, elapsed_ms=int((time.perf_counter() - t0) * 1000), detail=detail)


def _testing_enabled() -> bool:
    from airflow.configuration import conf

    return conf.get("core", "test_connection", fallback="Disabled").lower() == "enabled"


def _airflow_connection(conn_id: str):
    from airflow.hooks.base import BaseHook

    return BaseHook.get_connection(conn_id)


def probe_connection(connection: Connection) -> ProbeResult:
    t0 = time.perf_counter()
    if connection.connection_type == "local_fs":
        return _result(True, t0, "local filesystem")
    if not _testing_enabled():
        return _result(False, t0, "connection testing is disabled in Airflow; set "
                                  "[core] test_connection = Enabled to allow it")
    try:
        ok, detail = _airflow_connection(connection.id).test_connection()
    except Exception as e:
        return _result(False, t0, f"{type(e).__name__}: {e}")
    return _result(bool(ok), t0, detail or "")
