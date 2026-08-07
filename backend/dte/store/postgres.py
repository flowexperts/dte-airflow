import json
import uuid
from contextlib import asynccontextmanager

from sqlalchemy import func as sa_func
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from dte.models.pipeline import (
    Connection,
    ConnectionBase,
    Destination,
    DestinationBase,
    LookupTable,
    LookupTableBase,
    Pipeline,
    PipelineRevision,
    PipelineRevisionBase,
    Source,
    SourceBase,
)
from dte.models.user import Role, User, UserBase, UserRoleLink
from dte.tenancy import get_current_tenant


def _quality_summary_dicts(results: list[dict]) -> dict:
    """Compute pass/fail/warn counts from a list of raw quality_checks dicts."""
    passed = sum(1 for r in results if r.get("passed"))
    warned = sum(1 for r in results if not r.get("passed") and r.get("severity") == "warn")
    failed = sum(1 for r in results if not r.get("passed") and r.get("severity") == "fail")
    return {"passed": passed, "failed": failed, "warned": warned}


@asynccontextmanager
async def _open_tenant_session(factory: async_sessionmaker[AsyncSession]):
    """Context manager that opens a Postgres session and immediately emits
    ``SET LOCAL dte.tenant_id = '<tid>'`` so the RLS policy on every
    tenant-scoped table filters to the current request's tenant.

    Why here and not in a SQLAlchemy event hook?
      An ``after_begin`` hook fires on the *connection* (not the session),
      requires synchronous execution, and would affect every connection in the
      pool — not just the current request.  A tiny async context manager is
      easier to audit, test, and reason about, and has zero pool blast radius.

    Usage::

        async with _open_tenant_session(self._factory) as s:
            ...

    The SET LOCAL is scoped to the transaction, so it is reset automatically
    when the session commits or rolls back — no explicit cleanup needed.
    """
    async with factory() as session:
        tid = get_current_tenant()
        # Postgres does not accept bind parameters for SET LOCAL, so use
        # set_config(name, value, is_local=true) — same effect, and it
        # does accept parameters, keeping tid safely out of the SQL text.
        await session.execute(
            text("SELECT set_config('dte.tenant_id', :tid, true)"),
            {"tid": tid},
        )
        yield session


class PostgresPipelineStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> Pipeline | None:
        async with _open_tenant_session(self._factory) as s:
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
                "engine": stmt.excluded.engine,
                "quality_contracts": stmt.excluded.quality_contracts,
                "params": stmt.excluded.params,
            },
        )
        async with _open_tenant_session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[Pipeline]:
        stmt = (
            select(Pipeline)
            .order_by(Pipeline.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with _open_tenant_session(self._factory) as s:
            return list((await s.execute(stmt)).scalars().all())

    async def delete(self, id: str) -> bool:
        async with _open_tenant_session(self._factory) as s:
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
        async with _open_tenant_session(self._factory) as s:
            result = await s.execute(
                text("SELECT id, pipeline_id, revision_id, status, error, rows_written, location, started_at, finished_at, params, quality_checks, sql_query, job_id, last_heartbeat_at FROM runs WHERE id = :id"),
                {"id": id}
            )
            row = result.mappings().fetchone()
            if not row:
                return None
            d = dict(row)
            d["started_at"] = d["started_at"].isoformat() if d.get("started_at") else None
            d["finished_at"] = d["finished_at"].isoformat() if d.get("finished_at") else None
            d["last_heartbeat_at"] = d["last_heartbeat_at"].isoformat() if d.get("last_heartbeat_at") else None
            raw_quality = list(d.pop("quality_checks") or [])
            d["quality"] = _quality_summary_dicts(raw_quality)
            return d

    async def create(self, pipeline_id: str, revision_id: str | None = None) -> str:
        run_id = str(uuid.uuid4())
        async with _open_tenant_session(self._factory) as s:
            await s.execute(text("""
                INSERT INTO runs (id, pipeline_id, revision_id, status)
                VALUES (:id, :pipeline_id, :revision_id, 'pending')
            """), {"id": run_id, "pipeline_id": pipeline_id, "revision_id": revision_id})
            await s.commit()
        return run_id

    async def update(self, id: str, **fields) -> None:
        if not fields:
            return
        # `params` lives in a jsonb column; asyncpg won't auto-encode a Python
        # dict for a text bind, so serialise + cast at the SQL layer.
        import json as _json
        assignments = []
        binds: dict = {"id": id}
        for k, v in fields.items():
            if k in ("params", "sql_query") and isinstance(v, dict | list):
                assignments.append(f"{k} = CAST(:{k} AS jsonb)")
                binds[k] = _json.dumps(v)
            else:
                assignments.append(f"{k} = :{k}")
                binds[k] = v
        set_clause = ", ".join(assignments)
        async with _open_tenant_session(self._factory) as s:
            await s.execute(
                text(f"UPDATE runs SET {set_clause} WHERE id = :id"),
                binds,
            )
            await s.commit()

    async def list_for_pipeline(self, pipeline_id: str, limit: int = 50) -> list[dict]:
        async with _open_tenant_session(self._factory) as s:
            result = await s.execute(
                text("SELECT id, pipeline_id, revision_id, status, error, rows_written, location, started_at, finished_at, params, quality_checks, sql_query, job_id, last_heartbeat_at FROM runs WHERE pipeline_id = :pid ORDER BY started_at DESC LIMIT :limit"),
                {"pid": pipeline_id, "limit": limit}
            )
            rows = []
            for row in result.mappings().fetchall():
                d = dict(row)
                d["started_at"] = d["started_at"].isoformat() if d.get("started_at") else None
                d["finished_at"] = d["finished_at"].isoformat() if d.get("finished_at") else None
                d["last_heartbeat_at"] = d["last_heartbeat_at"].isoformat() if d.get("last_heartbeat_at") else None
                raw_quality = list(d.pop("quality_checks") or [])
                d["quality"] = _quality_summary_dicts(raw_quality)
                rows.append(d)
            return rows

    async def delete_for_pipeline(self, pipeline_id: str) -> int:
        async with _open_tenant_session(self._factory) as s:
            result = await s.execute(
                text("DELETE FROM runs WHERE pipeline_id = :pid"), {"pid": pipeline_id}
            )
            await s.commit()
            return result.rowcount

    async def set_quality(self, run_id: str, results: list) -> None:
        serialised = [
            r.model_dump() if hasattr(r, "model_dump") else r
            for r in results
        ]
        async with _open_tenant_session(self._factory) as s:
            await s.execute(
                text("UPDATE runs SET quality_checks = CAST(:v AS jsonb) WHERE id = :id"),
                {"v": json.dumps(serialised), "id": run_id},
            )
            await s.commit()

    async def get_quality(self, run_id: str) -> list:
        async with _open_tenant_session(self._factory) as s:
            result = await s.execute(
                text("SELECT quality_checks FROM runs WHERE id = :id"),
                {"id": run_id},
            )
            row = result.mappings().fetchone()
            return list(row["quality_checks"] or []) if row else []


class PostgresPipelineRevisionStore:
    """Append-only history of pipeline configs. One row per accepted
    POST/PUT. Never upserts — the `id` is generated per-write."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def save(self, revision: "PipelineRevisionBase | PipelineRevision") -> None:
        stmt = pg_insert(PipelineRevision).values(
            id=revision.id,
            pipeline_id=revision.pipeline_id,
            config=revision.config,
            changed_by=revision.changed_by,
            summary=revision.summary,
        )
        async with _open_tenant_session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def get(self, id: str) -> PipelineRevision | None:
        async with _open_tenant_session(self._factory) as s:
            return await s.get(PipelineRevision, id)

    async def list_for_pipeline(
        self, pipeline_id: str, limit: int = 100
    ) -> list[PipelineRevision]:
        stmt = (
            select(PipelineRevision)
            .where(PipelineRevision.pipeline_id == pipeline_id)
            .order_by(PipelineRevision.changed_at.desc())
            .limit(limit)
        )
        async with _open_tenant_session(self._factory) as s:
            return list((await s.execute(stmt)).scalars().all())

    async def latest_for_pipeline(self, pipeline_id: str) -> PipelineRevision | None:
        stmt = (
            select(PipelineRevision)
            .where(PipelineRevision.pipeline_id == pipeline_id)
            .order_by(PipelineRevision.changed_at.desc())
            .limit(1)
        )
        async with _open_tenant_session(self._factory) as s:
            return (await s.execute(stmt)).scalars().first()


class PostgresRunEventStore:
    """Postgres-backed run events. Uses ON CONFLICT to upsert per (run, step)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def record(
        self,
        run_id: str,
        step_index: int,
        op: str,
        status: str,
        message: str | None = None,
    ) -> None:
        # Deterministic id so "started" and later "completed"/"failed" for the
        # same step upsert onto one row.
        row_id = f"{run_id}:{step_index}"
        async with _open_tenant_session(self._factory) as s:
            await s.execute(
                text("""
                    INSERT INTO run_events (id, run_id, step_index, op, status, message,
                                            started_at, finished_at)
                    VALUES (:id, :rid, :idx, :op, :status, :msg,
                            NOW(),
                            CASE WHEN :status IN ('completed','failed','skipped')
                                 THEN NOW() ELSE NULL END)
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        message = EXCLUDED.message,
                        finished_at = EXCLUDED.finished_at
                """),
                {
                    "id": row_id, "rid": run_id, "idx": step_index,
                    "op": op, "status": status, "msg": message,
                },
            )
            await s.commit()

    async def list_for_run(self, run_id: str) -> list[dict]:
        async with _open_tenant_session(self._factory) as s:
            result = await s.execute(
                text(
                    "SELECT step_index, op, status, message, started_at, finished_at "
                    "FROM run_events WHERE run_id = :rid ORDER BY step_index, started_at"
                ),
                {"rid": run_id},
            )
            rows = []
            for row in result.mappings().fetchall():
                d = dict(row)
                d["started_at"] = d["started_at"].isoformat() if d.get("started_at") else None
                d["finished_at"] = d["finished_at"].isoformat() if d.get("finished_at") else None
                rows.append(d)
            return rows


class PostgresSourceStore:
    """ORM-backed source store. Returns typed `Source` instances.

    `save` accepts a `Source` or `SourceBase` instance. The store uses
    pg_insert upsert so `updated_at` fires on re-save.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> Source | None:
        async with _open_tenant_session(self._factory) as s:
            return await s.get(Source, id)

    async def save(self, source: "SourceBase | Source") -> None:
        values = source.model_dump(exclude={"created_at", "updated_at"})
        # Guarantee name is set — historic callers may pass a Source ORM
        # instance whose validator never ran.
        if not values.get("name"):
            values["name"] = values["id"]
        stmt = pg_insert(Source).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Source.id],
            set_={
                "name": stmt.excluded.name,
                "source_type": stmt.excluded.source_type,
                "config": stmt.excluded.config,
                "table_name": stmt.excluded.table_name,
                "connection_id": stmt.excluded.connection_id,
                "format": stmt.excluded.format,
            },
        )
        async with _open_tenant_session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[Source]:
        stmt = (
            select(Source)
            .order_by(Source.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with _open_tenant_session(self._factory) as s:
            return list((await s.execute(stmt)).scalars().all())

    async def delete(self, id: str) -> bool:
        async with _open_tenant_session(self._factory) as s:
            row = await s.get(Source, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True


class PostgresDestinationStore:
    """ORM-backed destination store. Returns typed `Destination` instances.

    `save` accepts a `Destination` or `DestinationBase` instance. The store
    uses pg_insert upsert so `updated_at` fires on re-save. `config` is
    serialised to a plain dict for JSONB storage; on read, `narrow_config()`
    is called explicitly (table=True bypasses validators on hydration).

    `dest_type` is a denormalised column kept for backward compat; it is written
    explicitly at save time from `config.type` (drop in a follow-up migration).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> Destination | None:
        async with _open_tenant_session(self._factory) as s:
            row = await s.get(Destination, id)
            if row is None:
                return None
            return row.narrow_config()

    async def save(self, destination: "DestinationBase | Destination") -> None:
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
            name=destination.name or destination.id,
            connection_id=destination.connection_id,
            config=config_dict,
            dest_type=dest_type,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Destination.id],
            set_={
                "name": stmt.excluded.name,
                "connection_id": stmt.excluded.connection_id,
                "config": stmt.excluded.config,
                "dest_type": stmt.excluded.dest_type,
            },
        )
        async with _open_tenant_session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[Destination]:
        stmt = (
            select(Destination)
            .order_by(Destination.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with _open_tenant_session(self._factory) as s:
            rows = list((await s.execute(stmt)).scalars().all())
        return [row.narrow_config() for row in rows]

    async def delete(self, id: str) -> bool:
        async with _open_tenant_session(self._factory) as s:
            row = await s.get(Destination, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True


class PostgresLookupTableStore:
    """ORM-backed lookup table store. Returns typed `LookupTable` instances."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> LookupTable | None:
        async with _open_tenant_session(self._factory) as s:
            return await s.get(LookupTable, id)

    async def save(self, lookup: "LookupTableBase | LookupTable") -> None:
        values = {
            "id": lookup.id,
            "name": lookup.name or lookup.id,
            "mappings": lookup.mappings,
            "default": lookup.default,
        }
        stmt = pg_insert(LookupTable).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[LookupTable.id],
            set_={
                "name": stmt.excluded.name,
                "mappings": stmt.excluded.mappings,
                "default": stmt.excluded.default,
            },
        )
        async with _open_tenant_session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[LookupTable]:
        stmt = (
            select(LookupTable)
            .order_by(LookupTable.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with _open_tenant_session(self._factory) as s:
            return list((await s.execute(stmt)).scalars().all())

    async def delete(self, id: str) -> bool:
        async with _open_tenant_session(self._factory) as s:
            row = await s.get(LookupTable, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True


class PostgresConnectionStore:
    """Stores connection rows with credentials encrypted at rest via
    `EncryptedJSON` — the TypeDecorator handles encrypt/decrypt
    transparently at the column level.  No `SecretResolver` needed here.

    Returns typed `Connection` instances. `credentials` is now a real
    mapped column (not a detached attribute), so `model_dump()` and
    attribute access both work naturally.

    `list` returns rows with credentials masked to `{}` — masking is done
    by model_copy so the store never exposes plaintext on the list path.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> Connection | None:
        async with _open_tenant_session(self._factory) as s:
            return await s.get(Connection, id)

    async def save(self, connection: "ConnectionBase | Connection") -> None:
        stmt = pg_insert(Connection).values(
            id=connection.id,
            name=connection.name or connection.id,
            connection_type=connection.connection_type,
            credentials=connection.credentials,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[Connection.id],
            set_={
                "name": stmt.excluded.name,
                "connection_type": stmt.excluded.connection_type,
                # Physical column name is `credentials_encrypted` (TypeDecorator alias).
                "credentials_encrypted": stmt.excluded.credentials_encrypted,
            },
        )
        async with _open_tenant_session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[Connection]:
        """Returns rows with credentials masked (empty dict) — never exposes plaintext."""
        stmt = (
            select(Connection)
            .order_by(Connection.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with _open_tenant_session(self._factory) as s:
            rows = list((await s.execute(stmt)).scalars().all())
        # Return copies with masked credentials so callers never see plaintext.
        masked = []
        for row in rows:
            masked_row = Connection(
                id=row.id,
                name=row.name,
                connection_type=row.connection_type,
                credentials={},
            )
            masked.append(masked_row)
        return masked

    async def delete(self, id: str) -> bool:
        async with _open_tenant_session(self._factory) as s:
            row = await s.get(Connection, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True


class PostgresUserStore:
    """ORM-backed user store. Returns typed `User` instances.

    `password_hash` is passed separately to `save` so the caller
    (the register route) hashes once and the store never receives
    plaintext. This mirrors the pattern used by all other Postgres
    stores — `pg_insert(...).on_conflict_do_update(...)` so that
    `updated_at` fires on re-save.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def _load_roles(self, s: AsyncSession, user: User) -> None:
        role_stmt = (
            select(Role)
            .join(UserRoleLink, UserRoleLink.role_id == Role.id)
            .where(UserRoleLink.user_id == user.id)
        )
        roles = list((await s.execute(role_stmt)).scalars().all())
        user.narrow_roles(roles)

    async def get_by_id(self, id: str) -> User | None:
        async with _open_tenant_session(self._factory) as s:
            row = await s.get(User, id)
            if row is not None:
                await self._load_roles(s, row)
            return row

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        async with _open_tenant_session(self._factory) as s:
            row = (await s.execute(stmt)).scalars().first()
            if row is not None:
                await self._load_roles(s, row)
            return row

    async def save(self, user: "UserBase", password_hash: str) -> None:
        stmt = pg_insert(User).values(
            id=user.id,
            email=str(user.email),
            is_active=user.is_active,
            password_hash=password_hash,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[User.id],
            set_={
                "email": stmt.excluded.email,
                "is_active": stmt.excluded.is_active,
                "password_hash": stmt.excluded.password_hash,
            },
        )
        async with _open_tenant_session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def list(self, limit: int = 50, offset: int = 0) -> list[User]:
        stmt = (
            select(User)
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        async with _open_tenant_session(self._factory) as s:
            rows = list((await s.execute(stmt)).scalars().all())
            for row in rows:
                await self._load_roles(s, row)
            return rows

    async def delete(self, id: str) -> bool:
        async with _open_tenant_session(self._factory) as s:
            row = await s.get(User, id)
            if row is None:
                return False
            await s.delete(row)
            await s.commit()
            return True

    async def count(self) -> int:
        async with _open_tenant_session(self._factory) as s:
            return int((await s.execute(select(sa_func.count()).select_from(User))).scalar_one())

    async def add_role(self, user_id: str, role_id: str) -> None:
        stmt = pg_insert(UserRoleLink).values(user_id=user_id, role_id=role_id)
        stmt = stmt.on_conflict_do_nothing(index_elements=[UserRoleLink.user_id, UserRoleLink.role_id])
        async with _open_tenant_session(self._factory) as s:
            await s.execute(stmt)
            await s.commit()

    async def remove_role(self, user_id: str, role_id: str) -> bool:
        async with _open_tenant_session(self._factory) as s:
            link = await s.get(UserRoleLink, (user_id, role_id))
            if link is None:
                return False
            await s.delete(link)
            await s.commit()
            return True


class PostgresRoleStore:
    # `roles` and `user_roles` are NOT in the RLS-protected table list
    # (migration 016 explicitly excludes them — they are tenant-agnostic RBAC
    # tables).  These methods intentionally bypass _open_tenant_session.
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._factory = session_factory

    async def get(self, id: str) -> Role | None:
        async with self._factory() as s:  # no tenant context — RBAC table, not RLS-protected
            return await s.get(Role, id)

    async def list(self) -> list[Role]:
        async with self._factory() as s:  # no tenant context — RBAC table, not RLS-protected
            return list((await s.execute(select(Role).order_by(Role.name))).scalars().all())
