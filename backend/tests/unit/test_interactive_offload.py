"""Interactive routes must not block the event loop (plan 084).

DTE is mounted inside Airflow's api-server, so a sync source load inside an
`async def` route stalls every request on that worker — run history,
Airflow's own UI, health checks — for as long as the source takes.
"""
import asyncio
import time

import httpx
import pytest

from dte.api.main import app
from dte.models.pipeline import DestinationCreate, Pipeline, SourceCreate

SLOW = 1.0

SOURCE = {
    "id": "src", "connection_id": "local_fs", "source_type": "filesystem",
    "config": {"bucket_url": "/nowhere", "file_glob": "x.json"}, "table": "x",
}
PIPELINE = {"id": "p1", "name": "p", "sources": ["src"], "steps": [], "output_id": "out1"}

ROUTES = [
    ("POST", "/api/schema/infer", SOURCE),
    ("GET", "/api/sources/src/schema", None),
    ("POST", "/api/pipelines/step-schemas", PIPELINE),
    ("POST", "/api/pipelines/dry-run", PIPELINE),
    ("GET", "/api/pipelines/p1/preview", None),
]


def _run(coro):
    # Not asyncio.run(): it leaves no current loop behind, and later tests
    # in the suite still call asyncio.get_event_loop().
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _slow_load(*args, **kwargs):
    time.sleep(SLOW)
    raise ValueError("slow source")


@pytest.fixture
def seeded(fake_stores, monkeypatch, tmp_path):
    for mod in ("pipelines", "schema"):
        monkeypatch.setattr(f"dte.api.routes.{mod}.load_source", _slow_load)
    _run(fake_stores["source"].save(SourceCreate(**SOURCE)))
    _run(fake_stores["destination"].save(DestinationCreate(
        id="out1", connection_id="local_fs",
        config={"type": "json_file", "path": str(tmp_path / "o.json")},
    )))
    _run(fake_stores["pipeline"].save(Pipeline(**PIPELINE)))


@pytest.mark.parametrize("method,path,body", ROUTES, ids=[p for _, p, _ in ROUTES])
def test_slow_source_does_not_block_other_requests(seeded, method, path, body):
    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            slow = asyncio.create_task(c.request(method, path, json=body))
            # A blocked loop stalls this sleep too, so time from before it.
            t0 = time.perf_counter()
            await asyncio.sleep(0.1)
            r = await c.get("/healthz")
            elapsed = time.perf_counter() - t0
            await slow
            return r, elapsed

    r, elapsed = _run(go())
    assert r.status_code == 200
    assert elapsed < SLOW / 2, f"/healthz waited {elapsed:.2f}s behind {path}"


@pytest.mark.parametrize("method,path,body", ROUTES, ids=[p for _, p, _ in ROUTES])
def test_interactive_routes_load_a_bounded_sample(seeded, monkeypatch, method, path, body):
    """Runs read the whole source; the editor reads `SAMPLE_ROWS` of it."""
    from fastapi.testclient import TestClient

    from dte.api.interactive import SAMPLE_ROWS

    seen = []

    def capture(*args, **kwargs):
        seen.append(kwargs.get("sample"))
        raise ValueError("stop here")

    for mod in ("pipelines", "schema"):
        monkeypatch.setattr(f"dte.api.routes.{mod}.load_source", capture)
    TestClient(app).request(method, path, json=body)
    assert seen == [SAMPLE_ROWS]
