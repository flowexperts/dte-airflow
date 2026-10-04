"""ConnectionStore over Airflow Connections (read-only)."""
from __future__ import annotations

import asyncio

from dte.airflow.connections import from_airflow
from dte.models.pipeline import Connection


def _rows(conn_id: str | None, limit: int, offset: int):
    from sqlalchemy import select

    from airflow.models.connection import Connection as AConn
    from airflow.utils.session import create_session

    with create_session() as s:
        q = select(AConn).order_by(AConn.conn_id)
        q = q.where(AConn.conn_id == conn_id) if conn_id else q.limit(limit).offset(offset)
        out = []
        for row in s.scalars(q):
            try:
                out.append(from_airflow(row))
            except (ValueError, KeyError):
                continue  # a type DTE can't map (redis, ...) is simply not offered
        return out


class AirflowConnectionStore:
    async def get(self, id: str) -> Connection | None:
        rows = await asyncio.to_thread(_rows, id, 1, 0)
        return rows[0] if rows else None

    async def list(self, limit: int = 50, offset: int = 0) -> list[Connection]:
        rows = await asyncio.to_thread(_rows, None, limit, offset)
        return [Connection.model_construct(id=c.id, name=c.name, connection_type=c.connection_type,
                                           credentials={}, tenant_id="default") for c in rows]
