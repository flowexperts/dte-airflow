from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select
import uuid
import json

from dte.models.pipeline import Connection, ConnectionCreate, Destination, DestinationCreate, Pipeline, Source, SourceCreate
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
    """ORM-backed source store. Returns typed `Source` instances.

    `save` accepts a `SourceCreate` (the strict API input type). The store
    uses pg_insert upsert so `updated_at` fires on re-save.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> Source | None:
        async with self._factory() as s:
            return await s.get(Source, id)

    async def save(self, source: SourceCreate) -> None:
        values = source.model_dump(exclude={"created_at", "updated_at"})
        stmt = pg_insert(Source).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Source.id],
            set_={
                "source_type": stmt.excluded.source_type,
                "config": stmt.excluded.config,
                "table_name": stmt.excluded.table_name,
                "connection_id": stmt.excluded.connection_id,
                "format": stmt.excluded.format,
            },
        )
        async with self._factory() as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[Source]:
        stmt = (
            select(Source)
            .order_by(Source.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._factory() as s:
            return list((await s.execute(stmt)).scalars().all())

    async def delete(self, id: str) -> bool:
        async with self._factory() as s:
            row = await s.get(Source, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True


class PostgresDestinationStore:
    """ORM-backed destination store. Returns typed `Destination` instances.

    `save` accepts a `DestinationCreate` (the strict API input type). The store
    uses pg_insert upsert so `updated_at` fires on re-save. `config` is
    serialised to a plain dict for JSONB storage; on read, `Destination`'s
    `_narrow_config` validator automatically narrows it back to the typed
    `OutputTarget` union — no extra work needed in `get`/`list`.

    `dest_type` is a denormalised column kept for backward compat; it is written
    explicitly at save time from `config.type` (drop in a follow-up migration).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> Destination | None:
        async with self._factory() as s:
            row = await s.get(Destination, id)
            if row is None:
                return None
            return row.narrow_config()

    async def save(self, destination: "DestinationCreate") -> None:
        # Serialise config to a plain dict for JSONB storage. The `config`
        # field is the typed OutputTarget union in memory; model_dump gives
        # back a JSON-serialisable dict. `by_alias=True` so `schema_` → `schema`.
        cfg = destination.config
        if hasattr(cfg, "model_dump"):
            config_dict = cfg.model_dump(by_alias=True, exclude_none=True)
        else:
            config_dict = dict(cfg)  # already a plain dict
        dest_type = config_dict.get("type", "")

        stmt = pg_insert(Destination).values(
            id=destination.id,
            connection_id=destination.connection_id,
            config=config_dict,
            dest_type=dest_type,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Destination.id],
            set_={
                "connection_id": stmt.excluded.connection_id,
                "config": stmt.excluded.config,
                "dest_type": stmt.excluded.dest_type,
            },
        )
        async with self._factory() as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[Destination]:
        stmt = (
            select(Destination)
            .order_by(Destination.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._factory() as s:
            rows = list((await s.execute(stmt)).scalars().all())
        return [row.narrow_config() for row in rows]

    async def delete(self, id: str) -> bool:
        async with self._factory() as s:
            row = await s.get(Destination, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True


class PostgresConnectionStore:
    """Stores connection rows with credentials encrypted at rest via a
    `SecretResolver` (env-based JSON in dev; Fernet in prod).

    Returns typed `Connection` instances. `credentials` is NOT a mapped
    column — `get` decrypts and attaches it as a plain Python attribute;
    `list` attaches an empty dict (masking behaviour stays in the store).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        resolver: SecretResolver | None = None,
    ):
        self._factory = session_factory
        self._resolver = resolver or get_secret_resolver()

    def _hydrate(self, row: Connection, credentials: dict) -> Connection:
        """Attach decrypted credentials as a plain attribute."""
        object.__setattr__(row, "credentials", credentials)
        return row

    async def get(self, id: str) -> Connection | None:
        async with self._factory() as s:
            row = await s.get(Connection, id)
            if row is None:
                return None
            credentials = self._resolver.decrypt(bytes(row.credentials_encrypted))
            return self._hydrate(row, credentials)

    async def save(self, connection: ConnectionCreate) -> None:
        ciphertext = self._resolver.encrypt(connection.credentials or {})
        stmt = pg_insert(Connection).values(
            id=connection.id,
            connection_type=connection.connection_type,
            credentials_encrypted=ciphertext,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Connection.id],
            set_={
                "connection_type": stmt.excluded.connection_type,
                "credentials_encrypted": stmt.excluded.credentials_encrypted,
            },
        )
        async with self._factory() as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[Connection]:
        """Returns rows with credentials masked (empty dict) — never decrypts."""
        stmt = (
            select(Connection)
            .order_by(Connection.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with self._factory() as s:
            rows = list((await s.execute(stmt)).scalars().all())
        return [self._hydrate(row, {}) for row in rows]

    async def delete(self, id: str) -> bool:
        async with self._factory() as s:
            row = await s.get(Connection, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True
