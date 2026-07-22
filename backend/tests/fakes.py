"""In-memory Store implementations for use in tests.

Test-only. Not part of the shipped `dte` package. Production uses the
Postgres store exclusively.

Use via `app.dependency_overrides[get_pipeline_store] = lambda: FakePipelineStore()`.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from dte.models.pipeline import (
    Connection, ConnectionBase,
    Destination, DestinationBase,
    LookupTable, LookupTableBase,
    Pipeline, PipelineBase,
    Source, SourceBase,
)
from dte.models.user import Role, User, UserBase


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FakePipelineStore:
    def __init__(self):
        self._data: dict[str, Pipeline] = {}

    async def get(self, id: str) -> Pipeline | None:
        return self._data.get(id)

    async def save(self, pipeline: Pipeline) -> None:
        existing = self._data.get(pipeline.id)
        pipeline.created_at = existing.created_at if existing else _utcnow()
        pipeline.updated_at = _utcnow()
        self._data[pipeline.id] = pipeline

    async def list(self, limit: int = 50, offset: int = 0) -> list[Pipeline]:
        items = sorted(
            self._data.values(),
            key=lambda p: p.created_at or _utcnow(),
            reverse=True,
        )
        return items[offset:offset + limit]

    async def delete(self, id: str) -> bool:
        if id in self._data:
            del self._data[id]
            return True
        return False


class FakeRunStore:
    def __init__(self):
        self._data: dict[str, dict] = {}

    async def get(self, id: str) -> dict | None:
        return self._data.get(id)

    async def create(self, pipeline_id: str) -> str:
        run_id = str(uuid.uuid4())
        self._data[run_id] = {
            "id": run_id,
            "pipeline_id": pipeline_id,
            "status": "pending",
            "error": None,
            "rows_written": None,
            "location": None,
            "started_at": _utcnow_iso(),
            "finished_at": None,
        }
        return run_id

    async def update(self, id: str, **fields) -> None:
        if id not in self._data:
            return
        self._data[id].update(fields)
        run = self._data[id]
        if run.get("status") in ("completed", "failed") and run.get("finished_at") is None:
            run["finished_at"] = _utcnow_iso()

    async def list_for_pipeline(self, pipeline_id: str, limit: int = 50) -> list[dict]:
        return [r for r in self._data.values() if r["pipeline_id"] == pipeline_id][:limit]

    async def delete_for_pipeline(self, pipeline_id: str) -> int:
        to_remove = [rid for rid, r in self._data.items() if r["pipeline_id"] == pipeline_id]
        for rid in to_remove:
            del self._data[rid]
        return len(to_remove)


class FakeRunEventStore:
    def __init__(self):
        self._data: dict[tuple[str, int], dict] = {}

    async def record(
        self,
        run_id: str,
        step_index: int,
        op: str,
        status: str,
        message: str | None = None,
    ) -> None:
        key = (run_id, step_index)
        now = _utcnow_iso()
        existing = self._data.get(key)
        if existing is None:
            self._data[key] = {
                "step_index": step_index,
                "op": op,
                "status": status,
                "message": message,
                "started_at": now,
                "finished_at": now if status in ("completed", "failed", "skipped") else None,
            }
        else:
            existing["status"] = status
            existing["message"] = message
            if status in ("completed", "failed", "skipped"):
                existing["finished_at"] = now

    async def list_for_run(self, run_id: str) -> list[dict]:
        return [
            v for (rid, _), v in sorted(self._data.items(), key=lambda x: x[0][1])
            if rid == run_id
        ]


def _make_source(s: "SourceBase | Source | dict") -> Source:
    """Build a `Source` ORM instance from a `SourceBase`, `Source`, or a plain dict.

    Uses normal `Source(...)` construction so SQLAlchemy's SA instrumentation
    (`_sa_instance_state`) is properly initialised — `model_construct` bypasses
    it and causes AttributeError when setting attributes later.

    Validators on `SourceBase` are skipped because `Source` is `table=True`
    (SQLModel bypasses required-field checks on table classes).

    Dict input is tolerated for backwards compat with migration scripts and
    legacy test helpers that pre-date the typed store.
    """
    if isinstance(s, dict):
        return Source(
            id=s["id"],
            connection_id=s.get("connection_id", ""),
            source_type=s.get("source_type", ""),
            config=s.get("config", {}),
            table=s.get("table", ""),
            format=s.get("format"),
        )
    return Source(
        id=s.id,
        connection_id=s.connection_id,
        source_type=s.source_type,
        config=s.config,
        table=s.table,
        format=s.format,
    )


class FakeSourceStore:
    """In-memory source store for tests. Stores typed `Source` instances.

    `save` accepts `SourceBase` (the typed API input), `Source` (the table
    class), or a plain `dict` (for migration scripts and legacy test helpers).
    """

    def __init__(self):
        self._data: dict[str, Source] = {}

    async def get(self, id: str) -> Source | None:
        return self._data.get(id)

    async def save(self, source: "SourceBase | Source | dict") -> None:  # type: ignore[override]
        source_id = source["id"] if isinstance(source, dict) else source.id
        existing = self._data.get(source_id)
        row = _make_source(source)
        row.created_at = existing.created_at if existing else _utcnow()
        row.updated_at = _utcnow()
        self._data[source_id] = row

    async def list(self, limit: int = 50, offset: int = 0) -> list[Source]:
        items = sorted(
            self._data.values(),
            key=lambda src: src.created_at or _utcnow(),
            reverse=True,
        )
        return items[offset:offset + limit]

    async def delete(self, id: str) -> bool:
        if id in self._data:
            del self._data[id]
            return True
        return False


def _make_destination(d: "DestinationBase | Destination | dict") -> Destination:
    """Build a typed `Destination` ORM instance from a `DestinationBase`,
    `Destination`, or a plain dict, then call `narrow_config()` to ensure
    `config` is a typed `OutputTarget` union instance.

    Uses normal `Destination(...)` construction so SQLAlchemy's SA instrumentation
    (`_sa_instance_state`) is properly initialised. `table=True` bypasses
    Pydantic validators, so `narrow_config()` must be called explicitly — same
    pattern as `PostgresDestinationStore.get`/`list`.

    Dict input is tolerated for backwards compat with migration scripts and
    legacy test helpers that pre-date the typed store.
    """
    if isinstance(d, dict):
        config_raw = d.get("config", {})
        dest_type = config_raw.get("type", "") if isinstance(config_raw, dict) else ""
        row = Destination(
            id=d["id"],
            connection_id=d.get("connection_id", "local_fs"),
            config=config_raw,
            dest_type=dest_type,
        )
    else:
        # DestinationBase / Destination — _narrow_config may have run, so
        # config might already be typed.
        cfg = d.config
        if hasattr(cfg, "model_dump"):
            config_dict = cfg.model_dump(by_alias=True, exclude_none=True)
        else:
            config_dict = dict(cfg)  # type: ignore[arg-type]
        dest_type = config_dict.get("type", "")
        row = Destination(
            id=d.id,
            connection_id=d.connection_id,
            config=config_dict,
            dest_type=dest_type,
        )
    return row.narrow_config()


class FakeDestinationStore:
    """In-memory destination store for tests. Stores typed `Destination` instances.

    `save` accepts `DestinationBase` (the typed API input), `Destination` (the
    table class), or a plain `dict` (for migration scripts and legacy test helpers).
    """

    def __init__(self):
        self._data: dict[str, Destination] = {}

    async def get(self, id: str) -> Destination | None:
        return self._data.get(id)

    async def save(self, destination: "DestinationBase | Destination | dict") -> None:  # type: ignore[override]
        dest_id = destination["id"] if isinstance(destination, dict) else destination.id
        existing = self._data.get(dest_id)
        row = _make_destination(destination)
        row.created_at = existing.created_at if existing else _utcnow()
        row.updated_at = _utcnow()
        self._data[dest_id] = row

    async def list(self, limit: int = 50, offset: int = 0) -> list[Destination]:
        items = sorted(
            self._data.values(),
            key=lambda d: d.created_at or _utcnow(),
            reverse=True,
        )
        return items[offset:offset + limit]

    async def delete(self, id: str) -> bool:
        if id in self._data:
            del self._data[id]
            return True
        return False


class FakeLookupTableStore:
    """In-memory lookup table store for tests. Stores typed `LookupTable` instances.

    Accepts `LookupTableBase`, `LookupTable`, or a plain `dict` (for migration
    scripts) at `save()`.
    """

    def __init__(self):
        self._data: dict[str, LookupTable] = {}

    async def get(self, id: str) -> LookupTable | None:
        return self._data.get(id)

    async def save(self, lookup: "LookupTableBase | LookupTable | dict") -> None:
        if isinstance(lookup, dict):
            row = LookupTable(
                id=lookup["id"],
                name=lookup.get("name"),
                mappings=lookup.get("mappings", {}),
                default=lookup.get("default"),
            )
        else:
            row = LookupTable(
                id=lookup.id,
                name=lookup.name,
                mappings=lookup.mappings,
                default=lookup.default,
            )
        existing = self._data.get(row.id)
        row.created_at = existing.created_at if existing else _utcnow()
        row.updated_at = _utcnow()
        self._data[row.id] = row

    async def list(self, limit: int = 50, offset: int = 0) -> list[LookupTable]:
        items = sorted(
            self._data.values(),
            key=lambda lt: lt.created_at or _utcnow(),
            reverse=True,
        )
        return items[offset:offset + limit]

    async def delete(self, id: str) -> bool:
        if id in self._data:
            del self._data[id]
            return True
        return False


class FakeConnectionStore:
    """In-memory connection store for tests. Stores typed `Connection`
    instances; `credentials` is a real attribute on the Connection (backed
    by EncryptedJSON in Postgres, plain dict in the fake)."""

    def __init__(self):
        self._data: dict[str, Connection] = {}

    async def get(self, id: str) -> Connection | None:
        return self._data.get(id)

    async def save(self, connection: "ConnectionBase | Connection") -> None:
        existing = self._data.get(connection.id)
        row = Connection(
            id=connection.id,
            connection_type=connection.connection_type,
            credentials=connection.credentials,
        )
        # Preserve created_at if already saved (mirrors FakePipelineStore).
        if existing is not None:
            row.created_at = existing.created_at
        row.updated_at = _utcnow()
        self._data[connection.id] = row

    async def list(self, limit: int = 50, offset: int = 0) -> list[Connection]:
        items = list(self._data.values())
        # Mask: return copies with credentials={}
        masked = []
        for c in items[offset:offset + limit]:
            masked_row = Connection(
                id=c.id,
                connection_type=c.connection_type,
                credentials={},
            )
            masked.append(masked_row)
        return masked

    async def delete(self, id: str) -> bool:
        if id in self._data:
            del self._data[id]
            return True
        return False


class FakeUserStore:
    """In-memory user store for tests. Stores typed `User` instances.

    `save` accepts a `UserBase` instance plus a pre-hashed password.
    Mirrors the `UserStore` Protocol in `dte/store/base.py`.
    """

    def __init__(self, role_store: "FakeRoleStore | None" = None):
        self._data: dict[str, User] = {}
        # (user_id, role_id) pairs
        self._links: set[tuple[str, str]] = set()
        self._role_store = role_store

    def _attach_roles(self, user: User) -> User:
        if self._role_store is None:
            user.narrow_roles([])
            return user
        rids = [rid for uid, rid in self._links if uid == user.id]
        roles = [self._role_store._data[rid] for rid in rids if rid in self._role_store._data]
        user.narrow_roles(roles)
        return user

    async def get_by_id(self, id: str) -> User | None:
        u = self._data.get(id)
        return self._attach_roles(u) if u is not None else None

    async def get_by_email(self, email: str) -> User | None:
        for user in self._data.values():
            if user.email == email:
                return self._attach_roles(user)
        return None

    async def save(self, user: "UserBase", password_hash: str) -> None:
        existing = self._data.get(user.id)
        row = User(
            id=user.id,
            email=str(user.email),
            is_active=user.is_active,
            password_hash=password_hash,
        )
        row.created_at = existing.created_at if existing else _utcnow()
        row.updated_at = _utcnow()
        self._data[user.id] = row

    async def list(self, limit: int = 50, offset: int = 0) -> list[User]:
        items = sorted(
            self._data.values(),
            key=lambda u: u.created_at or _utcnow(),
            reverse=True,
        )
        return [self._attach_roles(u) for u in items[offset:offset + limit]]

    async def delete(self, id: str) -> bool:
        if id in self._data:
            del self._data[id]
            self._links = {(u, r) for (u, r) in self._links if u != id}
            return True
        return False

    async def count(self) -> int:
        return len(self._data)

    async def add_role(self, user_id: str, role_id: str) -> None:
        self._links.add((user_id, role_id))

    async def remove_role(self, user_id: str, role_id: str) -> bool:
        if (user_id, role_id) in self._links:
            self._links.discard((user_id, role_id))
            return True
        return False


class FakeRoleStore:
    def __init__(self):
        self._data: dict[str, Role] = {}

    async def get(self, id: str) -> Role | None:
        return self._data.get(id)

    async def list(self) -> list[Role]:
        return sorted(self._data.values(), key=lambda r: r.name)
