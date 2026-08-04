"""User-flow DSL for scenario tests.

Each helper corresponds to one user action against the real HTTP API.
Scenarios read as a script: create source → create dest → create pipeline
→ trigger → wait → read output.

All helpers are async and take an `httpx.AsyncClient`.
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from typing import Any


async def create_connection(
    client, *, id: str, connection_type: str, credentials: dict | None = None
) -> dict:
    """POST /api/connections. Skip for `local_fs` — pre-seeded in conftest."""
    payload = {
        "id": id,
        "connection_type": connection_type,
        "credentials": credentials or {},
    }
    r = await client.post("/api/connections", json=payload)
    assert r.status_code in (200, 201), f"create_connection failed: {r.status_code} {r.text}"
    return r.json()


async def create_source(
    client,
    *,
    id: str,
    source_type: str,
    connection_id: str,
    config: dict,
    table: str,
    format: str | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "id": id,
        "source_type": source_type,
        "connection_id": connection_id,
        "config": config,
        "table": table,
    }
    if format is not None:
        payload["format"] = format
    r = await client.post("/api/sources", json=payload)
    assert r.status_code in (200, 201), f"create_source failed: {r.status_code} {r.text}"
    return r.json()


async def create_destination(
    client, *, id: str, connection_id: str, config: dict
) -> dict:
    payload = {"id": id, "connection_id": connection_id, "config": config}
    r = await client.post("/api/destinations", json=payload)
    assert r.status_code in (200, 201), f"create_destination failed: {r.status_code} {r.text}"
    return r.json()


async def create_pipeline(
    client, *, id: str, name: str | None = None,
    sources: list[str], steps: list[dict], output_id: str | None = None,
    pipeline_type: str = "transform", **extra,
) -> dict:
    payload: dict[str, Any] = {
        "id": id,
        "name": name or id,
        "sources": sources,
        "steps": steps,
        "pipeline_type": pipeline_type,
        **extra,
    }
    if output_id is not None:
        payload["output_id"] = output_id
    r = await client.post("/api/pipelines", json=payload)
    assert r.status_code in (200, 201), f"create_pipeline failed: {r.status_code} {r.text}"
    return r.json()


async def create_lookup_table(
    client, *, id: str, mappings: dict[str, str],
    name: str | None = None, default: str | None = None,
) -> dict:
    payload = {"id": id, "name": name or id, "mappings": mappings, "default": default}
    r = await client.post("/api/lookup-tables", json=payload)
    assert r.status_code in (200, 201), f"create_lookup_table failed: {r.status_code} {r.text}"
    return r.json()


async def trigger_and_wait(client, pipeline_id: str, timeout: float = 15.0) -> dict:
    """Trigger the pipeline and poll /api/runs/{id} until terminal."""
    r = await client.post(f"/api/pipelines/{pipeline_id}/trigger")
    assert r.status_code == 200, f"trigger failed: {r.status_code} {r.text}"
    run_id = r.json()["run_id"]

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    run: dict = {}
    while loop.time() < deadline:
        r = await client.get(f"/api/runs/{run_id}")
        assert r.status_code == 200, r.text
        run = r.json()
        if run["status"] in ("completed", "failed", "failed_quality", "completed_with_warnings"):
            return run
        await asyncio.sleep(0.05)
    raise AssertionError(f"run {run_id} did not finish within {timeout}s (last: {run})")


def read_output_file(path: str | Path) -> list[dict]:
    """Read a `json_file` destination's output directly from disk.

    /api/runs/{id}/output caps at ~100 rows and re-serialises, so for
    exact-match assertions the on-disk file is the source of truth."""
    text = Path(path).read_text()
    data = json.loads(text)
    return data if isinstance(data, list) else [data]


def row_set(rows: list[dict], keys: list[str] | None = None) -> set[tuple]:
    """Project rows to (key, val) tuple-sets for order-independent equality."""
    if keys is None:
        return {tuple(sorted(r.items())) for r in rows}
    return {tuple((k, r.get(k)) for k in keys) for r in rows}
