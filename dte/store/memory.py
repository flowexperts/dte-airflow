import uuid
from datetime import datetime, timezone


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryPipelineStore:
    def __init__(self):
        self._data: dict[str, dict] = {}

    async def get(self, id: str) -> dict | None:
        return self._data.get(id)

    async def save(self, pipeline: dict) -> None:
        self._data[pipeline["id"]] = pipeline

    async def list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        items = list(self._data.values())
        return items[offset:offset + limit]

    async def delete(self, id: str) -> bool:
        if id in self._data:
            del self._data[id]
            return True
        return False


class MemoryRunStore:
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
