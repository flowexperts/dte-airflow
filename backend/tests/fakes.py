"""In-memory Store implementations for use in tests.

Test-only. Not part of the shipped `dte` package. Production uses the
Postgres store exclusively.

Use via `app.dependency_overrides[get_pipeline_store] = lambda: FakePipelineStore()`.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from dte.models.pipeline import Pipeline


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


class FakeSourceStore:
    def __init__(self):
        self._data: dict[str, dict] = {}

    async def get(self, id: str) -> dict | None:
        return self._data.get(id)

    async def save(self, source: dict) -> None:
        self._data[source["id"]] = source

    async def list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        items = list(self._data.values())
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


def _mask_credentials(connection: dict) -> dict:
    creds = connection.get("credentials") or {}
    masked = {k: "***" for k in creds}
    return {**connection, "credentials": masked}


class FakeConnectionStore:
    def __init__(self):
        self._data: dict[str, dict] = {}

    async def get(self, id: str) -> dict | None:
        entry = self._data.get(id)
        return dict(entry) if entry else None

    async def save(self, connection: dict) -> None:
        self._data[connection["id"]] = dict(connection)

    async def list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        items = [_mask_credentials(c) for c in self._data.values()]
        return items[offset:offset + limit]

    async def delete(self, id: str) -> bool:
        if id in self._data:
            del self._data[id]
            return True
        return False
