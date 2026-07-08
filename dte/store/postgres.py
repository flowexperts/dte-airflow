from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import uuid
import json


class PostgresPipelineStore:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, id: str) -> dict | None:
        result = await self._session.execute(
            text("SELECT definition FROM pipelines WHERE id = :id"), {"id": id}
        )
        row = result.fetchone()
        return row[0] if row else None

    async def save(self, pipeline: dict) -> None:
        await self._session.execute(text("""
            INSERT INTO pipelines (id, name, definition)
            VALUES (:id, :name, :definition::jsonb)
            ON CONFLICT (id) DO UPDATE SET definition = EXCLUDED.definition, updated_at = now()
        """), {"id": pipeline["id"], "name": pipeline["name"], "definition": json.dumps(pipeline)})
        await self._session.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        result = await self._session.execute(
            text("SELECT definition FROM pipelines ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
            {"limit": limit, "offset": offset}
        )
        return [row[0] for row in result.fetchall()]

    async def delete(self, id: str) -> bool:
        result = await self._session.execute(
            text("DELETE FROM pipelines WHERE id = :id"), {"id": id}
        )
        await self._session.commit()
        return result.rowcount > 0


class PostgresRunStore:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def get(self, id: str) -> dict | None:
        result = await self._session.execute(
            text("SELECT id, pipeline_id, status, error, rows_written, started_at, finished_at FROM runs WHERE id = :id"),
            {"id": id}
        )
        row = result.mappings().fetchone()
        if not row:
            return None
        d = dict(row)
        d["started_at"] = d["started_at"].isoformat() if d.get("started_at") else None
        d["finished_at"] = d["finished_at"].isoformat() if d.get("finished_at") else None
        return d

    async def create(self, pipeline_id: str) -> str:
        run_id = str(uuid.uuid4())
        await self._session.execute(text("""
            INSERT INTO runs (id, pipeline_id, status) VALUES (:id, :pipeline_id, 'pending')
        """), {"id": run_id, "pipeline_id": pipeline_id})
        await self._session.commit()
        return run_id

    async def update(self, id: str, **fields) -> None:
        if not fields:
            return
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        await self._session.execute(
            text(f"UPDATE runs SET {set_clause} WHERE id = :id"),
            {"id": id, **fields}
        )
        await self._session.commit()

    async def list_for_pipeline(self, pipeline_id: str, limit: int = 50) -> list[dict]:
        result = await self._session.execute(
            text("SELECT id, pipeline_id, status, error, rows_written, started_at, finished_at FROM runs WHERE pipeline_id = :pid ORDER BY started_at DESC LIMIT :limit"),
            {"pid": pipeline_id, "limit": limit}
        )
        rows = []
        for row in result.mappings().fetchall():
            d = dict(row)
            d["started_at"] = d["started_at"].isoformat() if d.get("started_at") else None
            d["finished_at"] = d["finished_at"].isoformat() if d.get("finished_at") else None
            rows.append(d)
        return rows
