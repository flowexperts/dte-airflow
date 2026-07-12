from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import text
import uuid
import json


class PostgresPipelineStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> dict | None:
        async with self._factory() as s:
            result = await s.execute(
                text("SELECT definition FROM pipelines WHERE id = :id"), {"id": id}
            )
            row = result.fetchone()
            return row[0] if row else None

    async def save(self, pipeline: dict) -> None:
        async with self._factory() as s:
            await s.execute(text("""
                INSERT INTO pipelines (id, name, definition)
                VALUES (:id, :name, CAST(:definition AS jsonb))
                ON CONFLICT (id) DO UPDATE SET definition = EXCLUDED.definition, updated_at = now()
            """), {"id": pipeline["id"], "name": pipeline["name"], "definition": json.dumps(pipeline)})
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        async with self._factory() as s:
            result = await s.execute(
                text("SELECT definition FROM pipelines ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
                {"limit": limit, "offset": offset}
            )
            return [row[0] for row in result.fetchall()]

    async def delete(self, id: str) -> bool:
        async with self._factory() as s:
            result = await s.execute(
                text("DELETE FROM pipelines WHERE id = :id"), {"id": id}
            )
            await s.commit()
            return result.rowcount > 0


class PostgresRunStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> dict | None:
        async with self._factory() as s:
            result = await s.execute(
                text("SELECT id, pipeline_id, status, error, rows_written, location, started_at, finished_at FROM runs WHERE id = :id"),
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
        async with self._factory() as s:
            await s.execute(text("""
                INSERT INTO runs (id, pipeline_id, status) VALUES (:id, :pipeline_id, 'pending')
            """), {"id": run_id, "pipeline_id": pipeline_id})
            await s.commit()
        return run_id

    async def update(self, id: str, **fields) -> None:
        if not fields:
            return
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        async with self._factory() as s:
            await s.execute(
                text(f"UPDATE runs SET {set_clause} WHERE id = :id"),
                {"id": id, **fields}
            )
            await s.commit()

    async def list_for_pipeline(self, pipeline_id: str, limit: int = 50) -> list[dict]:
        async with self._factory() as s:
            result = await s.execute(
                text("SELECT id, pipeline_id, status, error, rows_written, location, started_at, finished_at FROM runs WHERE pipeline_id = :pid ORDER BY started_at DESC LIMIT :limit"),
                {"pid": pipeline_id, "limit": limit}
            )
            rows = []
            for row in result.mappings().fetchall():
                d = dict(row)
                d["started_at"] = d["started_at"].isoformat() if d.get("started_at") else None
                d["finished_at"] = d["finished_at"].isoformat() if d.get("finished_at") else None
                rows.append(d)
            return rows

    async def delete_for_pipeline(self, pipeline_id: str) -> int:
        async with self._factory() as s:
            result = await s.execute(
                text("DELETE FROM runs WHERE pipeline_id = :pid"), {"pid": pipeline_id}
            )
            await s.commit()
            return result.rowcount
