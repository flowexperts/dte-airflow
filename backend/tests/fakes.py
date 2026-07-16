"""In-memory Store implementations for use in tests.

Test-only. Not part of the shipped `dte` package. Production uses the
Postgres store exclusively.

Use via `app.dependency_overrides[get_pipeline_store] = lambda: FakePipelineStore()`.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from dte.models.pipeline import Connection, ConnectionCreate, Pipeline, Source, SourceCreate


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


def _make_source(s: "SourceCreate | dict") -> Source:
    """Build a `Source` ORM instance from a `SourceCreate` or a plain dict.

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

    `save` accepts `SourceCreate` (the typed API input) or a plain `dict`
    (for migration scripts and legacy test helpers).
    """

    def __init__(self):
        self._data: dict[str, Source] = {}

    async def get(self, id: str) -> Source | None:
        return self._data.get(id)

    async def save(self, source: "SourceCreate | dict") -> None:  # type: ignore[override]
        source_id = source.id if isinstance(source, SourceCreate) else source["id"]
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


class FakeDestinationStore:
    def __init__(self):
        self._data: dict[str, dict] = {}

    async def get(self, id: str) -> dict | None:
        return self._data.get(id)

    async def save(self, destination: dict) -> None:
        self._data[destination["id"]] = destination

    async def list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        items = list(self._data.values())
        return items[offset:offset + limit]

    async def delete(self, id: str) -> bool:
        if id in self._data:
            del self._data[id]
            return True
        return False


def _make_connection(c: ConnectionCreate) -> Connection:
    """Build a `Connection` ORM instance from a `ConnectionCreate`, attaching
    `credentials` as a plain attribute (mirrors what the Postgres store does)."""
    row = Connection(
        id=c.id,
        connection_type=c.connection_type,
        credentials_encrypted=b"",  # fake store doesn't encrypt
    )
    object.__setattr__(row, "credentials", c.credentials)
    return row


class FakeConnectionStore:
    """In-memory connection store for tests. Stores typed `Connection`
    instances; `credentials` live as a plain attribute on each instance."""

    def __init__(self):
        self._data: dict[str, Connection] = {}

    async def get(self, id: str) -> Connection | None:
        return self._data.get(id)

    async def save(self, connection: ConnectionCreate) -> None:
        existing = self._data.get(connection.id)
        row = _make_connection(connection)
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
                credentials_encrypted=c.credentials_encrypted,
            )
            object.__setattr__(masked_row, "credentials", {})
            masked.append(masked_row)
        return masked

    async def delete(self, id: str) -> bool:
        if id in self._data:
            del self._data[id]
            return True
        return False
