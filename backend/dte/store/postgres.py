from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
import uuid
import json

from dte.models.pipeline import Pipeline
from dte.secrets import SecretResolver, get_secret_resolver


class PostgresPipelineStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> Pipeline | None:
        async with self._factory() as s:
            return await s.get(Pipeline, id)

    async def save(self, pipeline: Pipeline) -> None:
        # Upsert via ON CONFLICT so a re-save touches `updated_at`
        # (session.merge would leave the column's `onupdate` unfired).
        values = pipeline.model_dump(exclude={"created_at", "updated_at"})
        stmt = pg_insert(Pipeline).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Pipeline.id],
            set_={
                "name": stmt.excluded.name,
                "sources": stmt.excluded.sources,
                "steps": stmt.excluded.steps,
                "output_id": stmt.excluded.output_id,
            },
        )
        async with self._factory() as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[Pipeline]:
        stmt = (
            select(Pipeline)
            .order_by(Pipeline.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._factory() as s:
            return list((await s.execute(stmt)).scalars().all())

    async def delete(self, id: str) -> bool:
        async with self._factory() as s:
            row = await s.get(Pipeline, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True


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


class PostgresSourceStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> dict | None:
        async with self._factory() as s:
            result = await s.execute(
                text("SELECT id, source_type, config, table_name, connection_id FROM sources WHERE id = :id"),
                {"id": id},
            )
            row = result.mappings().fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "source_type": row["source_type"],
                "config": row["config"],
                "table": row["table_name"],
                "connection_id": row["connection_id"],
            }

    async def save(self, source: dict) -> None:
        async with self._factory() as s:
            await s.execute(text("""
                INSERT INTO sources (id, source_type, config, table_name, connection_id)
                VALUES (:id, :source_type, CAST(:config AS jsonb), :table_name, :connection_id)
                ON CONFLICT (id) DO UPDATE SET
                    source_type = EXCLUDED.source_type,
                    config = EXCLUDED.config,
                    table_name = EXCLUDED.table_name,
                    connection_id = EXCLUDED.connection_id,
                    updated_at = now()
            """), {
                "id": source["id"],
                "source_type": source["source_type"],
                "config": json.dumps(source.get("config", {})),
                "table_name": source["table"],
                "connection_id": source.get("connection_id"),
            })
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        async with self._factory() as s:
            result = await s.execute(
                text("SELECT id, source_type, config, table_name, connection_id FROM sources ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
                {"limit": limit, "offset": offset},
            )
            return [
                {
                    "id": row["id"],
                    "source_type": row["source_type"],
                    "config": row["config"],
                    "table": row["table_name"],
                    "connection_id": row["connection_id"],
                }
                for row in result.mappings().fetchall()
            ]

    async def delete(self, id: str) -> bool:
        async with self._factory() as s:
            result = await s.execute(
                text("DELETE FROM sources WHERE id = :id"), {"id": id}
            )
            await s.commit()
            return result.rowcount > 0


class PostgresDestinationStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> dict | None:
        async with self._factory() as s:
            result = await s.execute(
                text("SELECT id, config, connection_id FROM destinations WHERE id = :id"),
                {"id": id},
            )
            row = result.mappings().fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "config": row["config"],
                "connection_id": row["connection_id"],
            }

    async def save(self, destination: dict) -> None:
        async with self._factory() as s:
            config = destination["config"]
            await s.execute(text("""
                INSERT INTO destinations (id, dest_type, config, connection_id)
                VALUES (:id, :dest_type, CAST(:config AS jsonb), :connection_id)
                ON CONFLICT (id) DO UPDATE SET
                    dest_type = EXCLUDED.dest_type,
                    config = EXCLUDED.config,
                    connection_id = EXCLUDED.connection_id,
                    updated_at = now()
            """), {
                "id": destination["id"],
                "dest_type": config["type"],
                "config": json.dumps(config),
                "connection_id": destination.get("connection_id"),
            })
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        async with self._factory() as s:
            result = await s.execute(
                text("SELECT id, config, connection_id FROM destinations ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
                {"limit": limit, "offset": offset},
            )
            return [
                {
                    "id": row["id"],
                    "config": row["config"],
                    "connection_id": row["connection_id"],
                }
                for row in result.mappings().fetchall()
            ]

    async def delete(self, id: str) -> bool:
        async with self._factory() as s:
            result = await s.execute(
                text("DELETE FROM destinations WHERE id = :id"), {"id": id}
            )
            await s.commit()
            return result.rowcount > 0


class PostgresConnectionStore:
    """Stores connection rows with credentials encrypted at rest via a
    `SecretResolver` (env-based JSON in dev; Fernet in prod)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        resolver: SecretResolver | None = None,
    ):
        self._factory = session_factory
        self._resolver = resolver or get_secret_resolver()

    async def get(self, id: str) -> dict | None:
        async with self._factory() as s:
            result = await s.execute(
                text("SELECT id, connection_type, credentials_encrypted FROM connections WHERE id = :id"),
                {"id": id},
            )
            row = result.mappings().fetchone()
            if not row:
                return None
            credentials = self._resolver.decrypt(bytes(row["credentials_encrypted"]))
            return {
                "id": row["id"],
                "connection_type": row["connection_type"],
                "credentials": credentials,
            }

    async def save(self, connection: dict) -> None:
        ciphertext = self._resolver.encrypt(connection.get("credentials") or {})
        async with self._factory() as s:
            await s.execute(text("""
                INSERT INTO connections (id, connection_type, credentials_encrypted)
                VALUES (:id, :connection_type, :credentials_encrypted)
                ON CONFLICT (id) DO UPDATE SET
                    connection_type = EXCLUDED.connection_type,
                    credentials_encrypted = EXCLUDED.credentials_encrypted,
                    updated_at = now()
            """), {
                "id": connection["id"],
                "connection_type": connection["connection_type"],
                "credentials_encrypted": ciphertext,
            })
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """Returns rows with credentials **masked** — never decrypts."""
        async with self._factory() as s:
            result = await s.execute(
                text("SELECT id, connection_type FROM connections ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
                {"limit": limit, "offset": offset},
            )
            return [
                {
                    "id": row["id"],
                    "connection_type": row["connection_type"],
                    "credentials": {},
                }
                for row in result.mappings().fetchall()
            ]

    async def delete(self, id: str) -> bool:
        async with self._factory() as s:
            result = await s.execute(
                text("DELETE FROM connections WHERE id = :id"), {"id": id}
            )
            await s.commit()
            return result.rowcount > 0
