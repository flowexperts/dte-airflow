"""In-memory Store implementations for use in tests.

Test-only. Not part of the shipped `dte` package. Production uses the
Postgres store exclusively.

Use via `app.dependency_overrides[get_pipeline_store] = lambda: FakePipelineStore()`.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from dte.models.eval import (
    EvalExample, EvalExampleBase,
    EvalSet, EvalSetBase,
)
from dte.models.pipeline import (
    Connection, ConnectionBase,
    Destination, DestinationBase,
    LookupTable, LookupTableBase,
    Pipeline, PipelineBase,
    PipelineRevision, PipelineRevisionBase,
    Schedule, ScheduleBase,
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

    async def get(self, id: str, tenant_id: str | None = None) -> Pipeline | None:
        row = self._data.get(id)
        if row is None:
            return None
        if tenant_id is not None and row.tenant_id != tenant_id:
            return None
        return row

    async def save(self, pipeline: Pipeline) -> None:
        existing = self._data.get(pipeline.id)
        # UNIQUE(tenant_id, name) — mirrors DB constraint from migration 024.
        for other in self._data.values():
            if other.id == pipeline.id:
                continue
            if other.tenant_id == pipeline.tenant_id and other.name == pipeline.name:
                raise ValueError(
                    f"Pipeline name '{pipeline.name}' already exists for tenant '{pipeline.tenant_id}'"
                )
        pipeline.created_at = existing.created_at if existing else _utcnow()
        pipeline.updated_at = _utcnow()
        self._data[pipeline.id] = pipeline

    async def list(self, limit: int = 50, offset: int = 0, tenant_id: str | None = None) -> list[Pipeline]:
        items = list(self._data.values())
        if tenant_id is not None:
            items = [p for p in items if p.tenant_id == tenant_id]
        items = sorted(items, key=lambda p: p.created_at or _utcnow(), reverse=True)
        return items[offset:offset + limit]

    async def delete(self, id: str, tenant_id: str | None = None) -> bool:
        row = self._data.get(id)
        if row is None:
            return False
        if tenant_id is not None and row.tenant_id != tenant_id:
            return False
        del self._data[id]
        return True


_TERMINAL_STATUSES = frozenset({
    "completed", "failed", "completed_with_warnings", "failed_quality", "cancelled"
})


def _quality_summary(results: list) -> dict:
    """Compute {passed, failed, warned} counts from QualityResult objects or dicts."""
    def _get(r, key):
        return r[key] if isinstance(r, dict) else getattr(r, key)
    passed = sum(1 for r in results if _get(r, "passed"))
    warned = sum(1 for r in results if not _get(r, "passed") and _get(r, "severity") == "warn")
    failed = sum(1 for r in results if not _get(r, "passed") and _get(r, "severity") == "fail")
    return {"passed": passed, "failed": failed, "warned": warned}


class FakeRunStore:
    def __init__(self):
        self._data: dict[str, dict] = {}
        self._quality: dict[str, list] = {}  # run_id → list[QualityResult]

    async def get(self, id: str) -> dict | None:
        run = self._data.get(id)
        if run is None:
            return None
        # Return a copy with the quality summary embedded.
        run = dict(run)
        quality_results = self._quality.get(id, [])
        run["quality"] = _quality_summary(quality_results)
        return run

    async def create(self, pipeline_id: str, revision_id: str | None = None) -> str:
        run_id = str(uuid.uuid4())
        self._data[run_id] = {
            "id": run_id,
            "pipeline_id": pipeline_id,
            "revision_id": revision_id,
            "status": "pending",
            "error": None,
            "rows_written": None,
            "location": None,
            "started_at": _utcnow_iso(),
            "finished_at": None,
            "params": None,
            "sql_query": None,
            "job_id": None,
            "last_heartbeat_at": None,
            "schedule_id": None,
            # Plan 051. Present-but-null on every run, not only eval runs, so
            # a caller reading them off a transform run gets None rather than
            # a KeyError — same contract the Postgres select list gives.
            "eval_set_id": None,
            "labels_version": None,
            "config_digest": None,
            "sweep_id": None,
            "scores": None,
        }
        return run_id

    async def update(self, id: str, **fields) -> None:
        if id not in self._data:
            return
        self._data[id].update(fields)
        run = self._data[id]
        if run.get("status") in _TERMINAL_STATUSES and run.get("finished_at") is None:
            run["finished_at"] = _utcnow_iso()

    async def list_for_pipeline(
        self, pipeline_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        rows = [r for r in self._data.values() if r["pipeline_id"] == pipeline_id]
        return rows[offset : offset + limit]

    async def list_for_eval_set(
        self, eval_set_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        rows = [r for r in self._data.values() if r.get("eval_set_id") == eval_set_id]
        # Newest first, matching the Postgres `ORDER BY started_at DESC`.
        rows.reverse()
        return rows[offset : offset + limit]

    async def list_for_sweep(self, sweep_id: str, limit: int = 50) -> list[dict]:
        # Oldest first, matching the Postgres `ORDER BY started_at ASC` — the
        # comparison grid's columns follow the order the matrix declared.
        rows = [r for r in self._data.values() if r.get("sweep_id") == sweep_id]
        return rows[:limit]

    async def list_sweep_runs_for_root(
        self, root_pipeline_id: str, limit: int = 500
    ) -> list[dict]:
        rows = [
            r for r in self._data.values()
            if r.get("sweep_id")
            and (r["pipeline_id"] == root_pipeline_id
                 or r["pipeline_id"].startswith(f"{root_pipeline_id}__"))
        ]
        # Newest first, matching the Postgres `ORDER BY started_at DESC`.
        rows.reverse()
        return rows[:limit]

    async def count_for_pipeline(self, pipeline_id: str) -> int:
        return sum(1 for r in self._data.values() if r["pipeline_id"] == pipeline_id)

    async def delete_for_pipeline(self, pipeline_id: str) -> int:
        to_remove = [rid for rid, r in self._data.items() if r["pipeline_id"] == pipeline_id]
        for rid in to_remove:
            del self._data[rid]
        return len(to_remove)

    async def set_quality(self, run_id: str, results: list) -> None:
        """Store QualityResult list for a run."""
        self._quality[run_id] = list(results)

    async def get_quality(self, run_id: str) -> list:
        """Return QualityResult list for a run (empty list if none recorded)."""
        return list(self._quality.get(run_id, []))


class FakePipelineRevisionStore:
    """Append-only in-memory revision store for tests."""

    def __init__(self):
        self._data: dict[str, PipelineRevision] = {}

    async def save(self, revision: "PipelineRevisionBase | PipelineRevision") -> None:
        row = PipelineRevision(
            id=revision.id,
            pipeline_id=revision.pipeline_id,
            config=revision.config,
            changed_by=revision.changed_by,
            summary=revision.summary,
        )
        row.changed_at = _utcnow()
        self._data[row.id] = row

    async def get(self, id: str) -> PipelineRevision | None:
        return self._data.get(id)

    async def list_for_pipeline(
        self, pipeline_id: str, limit: int = 100, offset: int = 0
    ) -> list[PipelineRevision]:
        items = [r for r in self._data.values() if r.pipeline_id == pipeline_id]
        items.sort(key=lambda r: r.changed_at or _utcnow(), reverse=True)
        return items[offset : offset + limit]

    async def count_for_pipeline(self, pipeline_id: str) -> int:
        return sum(1 for r in self._data.values() if r.pipeline_id == pipeline_id)

    async def latest_for_pipeline(self, pipeline_id: str) -> PipelineRevision | None:
        items = await self.list_for_pipeline(pipeline_id, limit=1)
        return items[0] if items else None


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
        sid = s["id"]
        return Source(
            id=sid,
            name=s.get("name") or sid,
            connection_id=s.get("connection_id", ""),
            source_type=s.get("source_type", ""),
            config=s.get("config", {}),
            table=s.get("table", ""),
            format=s.get("format"),
            tenant_id=s.get("tenant_id", "default"),
        )
    return Source(
        id=s.id,
        name=getattr(s, "name", None) or s.id,
        connection_id=s.connection_id,
        source_type=s.source_type,
        config=s.config,
        table=s.table,
        format=s.format,
        tenant_id=getattr(s, "tenant_id", "default"),
    )


class FakeSourceStore:
    """In-memory source store for tests. Stores typed `Source` instances.

    `save` accepts `SourceBase` (the typed API input), `Source` (the table
    class), or a plain `dict` (for migration scripts and legacy test helpers).
    """

    def __init__(self):
        self._data: dict[str, Source] = {}

    async def get(self, id: str, tenant_id: str | None = None) -> Source | None:
        row = self._data.get(id)
        if row is None:
            return None
        if tenant_id is not None and row.tenant_id != tenant_id:
            return None
        return row

    async def save(self, source: "SourceBase | Source | dict") -> None:  # type: ignore[override]
        source_id = source["id"] if isinstance(source, dict) else source.id
        existing = self._data.get(source_id)
        row = _make_source(source)
        # UNIQUE(tenant_id, name) — mirrors DB constraint from migration 021.
        for other in self._data.values():
            if other.id == row.id:
                continue
            if other.tenant_id == row.tenant_id and (other.name or other.id) == (row.name or row.id):
                raise ValueError(
                    f"Source name '{row.name}' already exists for tenant '{row.tenant_id}'"
                )
        row.created_at = existing.created_at if existing else _utcnow()
        row.updated_at = _utcnow()
        self._data[source_id] = row

    async def list(self, limit: int = 50, offset: int = 0, tenant_id: str | None = None) -> list[Source]:
        items = list(self._data.values())
        if tenant_id is not None:
            items = [s for s in items if s.tenant_id == tenant_id]
        items = sorted(items, key=lambda src: src.created_at or _utcnow(), reverse=True)
        return items[offset:offset + limit]

    async def delete(self, id: str, tenant_id: str | None = None) -> bool:
        row = self._data.get(id)
        if row is None:
            return False
        if tenant_id is not None and row.tenant_id != tenant_id:
            return False
        del self._data[id]
        return True


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
        did = d["id"]
        config_raw = d.get("config", {})
        dest_type = config_raw.get("type", "") if isinstance(config_raw, dict) else ""
        row = Destination(
            id=did,
            name=d.get("name") or did,
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
            name=getattr(d, "name", None) or d.id,
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
        # UNIQUE(tenant_id, name) — mirrors DB constraint from migration 022.
        for other in self._data.values():
            if other.id == row.id:
                continue
            if other.tenant_id == row.tenant_id and (other.name or other.id) == (row.name or row.id):
                raise ValueError(
                    f"Destination name '{row.name}' already exists for tenant '{row.tenant_id}'"
                )
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
            lid = lookup["id"]
            row = LookupTable(
                id=lid,
                name=lookup.get("name") or lid,
                mappings=lookup.get("mappings", {}),
                default=lookup.get("default"),
                tenant_id=lookup.get("tenant_id", "default"),
            )
        else:
            row = LookupTable(
                id=lookup.id,
                name=lookup.name or lookup.id,
                mappings=lookup.mappings,
                default=lookup.default,
                tenant_id=getattr(lookup, "tenant_id", "default"),
            )
        # UNIQUE(tenant_id, name) — mirrors DB constraint from migration 023.
        for other in self._data.values():
            if other.id == row.id:
                continue
            if other.tenant_id == row.tenant_id and (other.name or other.id) == (row.name or row.id):
                raise ValueError(
                    f"Lookup table name '{row.name}' already exists for tenant '{row.tenant_id}'"
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


class FakeScheduleStore:
    """In-memory schedule store for tests. `list_due`/`advance` mirror the
    ticker-facing (RLS-bypassing) side of `PostgresScheduleStore` — no
    tenant filtering, since the real ticker deliberately sees every
    tenant's due schedules in one pass."""

    def __init__(self):
        self._data: dict[str, Schedule] = {}

    async def get(self, id: str) -> Schedule | None:
        return self._data.get(id)

    async def save(self, schedule: "ScheduleBase | Schedule") -> None:
        existing = self._data.get(schedule.id)
        row = Schedule(**schedule.model_dump(exclude={"created_at", "updated_at"}))
        row.created_at = existing.created_at if existing else _utcnow()
        row.updated_at = _utcnow()
        self._data[row.id] = row

    async def list_for_pipeline(self, pipeline_id: str) -> list[Schedule]:
        items = [s for s in self._data.values() if s.pipeline_id == pipeline_id]
        return sorted(items, key=lambda s: s.created_at or _utcnow(), reverse=True)

    async def list_for_eval_set(self, eval_set_id: str) -> list[Schedule]:
        items = [s for s in self._data.values() if s.eval_set_id == eval_set_id]
        return sorted(items, key=lambda s: s.created_at or _utcnow(), reverse=True)

    async def list_due(self, now: datetime) -> list[Schedule]:
        return [
            s for s in self._data.values()
            if s.enabled and s.next_run_at is not None and s.next_run_at <= now
        ]

    async def advance(self, id: str, **fields) -> None:
        row = self._data.get(id)
        if row is None:
            return
        for k, v in fields.items():
            setattr(row, k, v)

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
        name = connection.name or connection.id
        tenant_id = getattr(connection, "tenant_id", "default") or "default"
        # Enforce UNIQUE(tenant_id, name) — mirrors DB constraint from migration 020.
        for other in self._data.values():
            if other.id == connection.id:
                continue
            if getattr(other, "tenant_id", "default") == tenant_id and (other.name or other.id) == name:
                raise ValueError(
                    f"Connection name '{name}' already exists for tenant '{tenant_id}'"
                )
        row = Connection(
            id=connection.id,
            name=name,
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
                name=c.name,
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
            tenant_id=getattr(user, "tenant_id", "default") or "default",
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


class FakeEvalSetStore:
    """In-memory eval-set store. `bump_labels_version` mirrors the Postgres
    store's SQL increment — separate from `save` so a CRUD edit of the name
    cannot invalidate every score recorded against the set."""

    def __init__(self):
        self._data: dict[str, EvalSet] = {}

    async def get(self, id: str) -> EvalSet | None:
        return self._data.get(id)

    async def save(self, eval_set: "EvalSetBase | EvalSet") -> None:
        existing = self._data.get(eval_set.id)
        values = eval_set.model_dump(exclude={"created_at", "updated_at"})
        if existing is not None:
            # labels_version is owned by bump_labels_version, not by save.
            values["labels_version"] = existing.labels_version
        row = EvalSet(**values)
        row.created_at = existing.created_at if existing else _utcnow()
        row.updated_at = _utcnow()
        self._data[row.id] = row

    async def list(self, limit: int = 50, offset: int = 0) -> list[EvalSet]:
        items = sorted(
            self._data.values(), key=lambda e: e.created_at or _utcnow(), reverse=True
        )
        return items[offset : offset + limit]

    async def delete(self, id: str) -> bool:
        if id in self._data:
            del self._data[id]
            return True
        return False

    async def bump_labels_version(self, id: str) -> int:
        row = self._data.get(id)
        if row is None:
            return 0
        row.labels_version += 1
        row.updated_at = _utcnow()
        return row.labels_version


class FakeEvalExampleStore:
    """In-memory labeled-document store. Keyed by `(eval_set_id, doc_key)` —
    the same natural key the Postgres UNIQUE constraint enforces — so
    relabeling a document replaces its label rather than accumulating a second
    contradictory one."""

    def __init__(self):
        self._data: dict[tuple[str, str], EvalExample] = {}

    def _key(self, example) -> tuple[str, str]:
        return (example.eval_set_id, example.doc_key)

    async def get(self, id: str) -> EvalExample | None:
        return next((e for e in self._data.values() if e.id == id), None)

    async def get_by_doc_key(self, eval_set_id: str, doc_key: str) -> EvalExample | None:
        return self._data.get((eval_set_id, doc_key.lower()))

    async def save(self, example: "EvalExampleBase | EvalExample") -> None:
        key = self._key(example)
        existing = self._data.get(key)
        values = example.model_dump(exclude={"created_at", "updated_at"})
        if existing is not None:
            # The row identity belongs to the document, not to whatever id the
            # caller happened to mint for this write.
            values["id"] = existing.id
        row = EvalExample(**values)
        row.created_at = existing.created_at if existing else _utcnow()
        row.updated_at = _utcnow()
        self._data[key] = row

    async def list_for_set(
        self,
        eval_set_id: str,
        split: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[EvalExample]:
        items = [e for e in self._data.values() if e.eval_set_id == eval_set_id]
        if split is not None:
            items = [e for e in items if e.split == split]
        items.sort(key=lambda e: e.created_at or _utcnow())
        return items[offset : offset + limit]

    async def count_for_set(self, eval_set_id: str, split: str | None = None) -> int:
        return len(await self.list_for_set(eval_set_id, split=split, limit=10**9))

    async def count_by_label_source(self, eval_set_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._data.values():
            if e.eval_set_id == eval_set_id:
                counts[e.label_source] = counts.get(e.label_source, 0) + 1
        return counts

    async def delete(self, id: str) -> bool:
        key = next((k for k, e in self._data.items() if e.id == id), None)
        if key is None:
            return False
        del self._data[key]
        return True
