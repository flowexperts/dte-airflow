"""ConnectionStore over Airflow Connections (read-only, plan 074).

`get` resolves like any Airflow task does (secrets backends, `AIRFLOW_CONN_*`
env vars, then the metadata DB). `list` shows the metadata DB plus env-var
connections; secrets backends can't be enumerated. Only connections whose
provider is installed are offered.
"""
from __future__ import annotations

import asyncio
import os

from dte.airflow.connections import available_kinds, from_airflow
from dte.models.pipeline import Connection


def _get(conn_id: str):
    from airflow.hooks.base import BaseHook

    return BaseHook.get_connection(conn_id)


def _all_conn_ids() -> list[str]:
    from airflow.models.connection import Connection as AConn
    from airflow.utils.session import create_session
    from sqlalchemy import select

    with create_session() as s:
        ids = set(s.scalars(select(AConn.conn_id)))
    ids |= {k[len("AIRFLOW_CONN_"):].lower() for k in os.environ if k.startswith("AIRFLOW_CONN_")}
    return sorted(ids)


def _resolve(conn_id: str) -> Connection | None:
    try:
        c = from_airflow(_get(conn_id))
    except Exception:  # unknown id, unmapped type (redis, ...), or a provider that won't build a hook
        return None
    return c if c.connection_type in available_kinds() else None


class AirflowConnectionStore:
    async def get(self, id: str) -> Connection | None:
        return await asyncio.to_thread(_resolve, id)

    async def list(self, limit: int = 50, offset: int = 0) -> list[Connection]:
        def _list():
            rows = (_resolve(i) for i in _all_conn_ids())
            return [c for c in rows if c][offset:offset + limit]

        return [Connection.model_construct(id=c.id, name=c.name, connection_type=c.connection_type,
                                           credentials={}, tenant_id="default")
                for c in await asyncio.to_thread(_list)]
