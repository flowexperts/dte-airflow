"""Scenario suite conftest.

Wires an async httpx client against the FastAPI app in-process, plus a
`scenario_ids` fixture that mints unique ids and cleans them up in
reverse dependency order at teardown. All scenarios in this suite are
auto-marked `scenario`.

The parent `tests/conftest.py`'s autouse `fake_stores` fixture already:
  - overrides every store dep with an in-memory Fake*Store,
  - bypasses `get_current_user` with an admin user,
  - pre-seeds a `local_fs` connection.

We reuse that machinery — scenarios talk to the FastAPI app in-process
via `httpx.AsyncClient(transport=ASGITransport(app))`. The Docker /
real-services matrix (plan 024 §2) is deferred.

Why async instead of starlette TestClient?
--------------------------------------------
Trigger routes spawn `asyncio.create_task(...)` that execute pipelines
via DuckDB + pyarrow. TestClient's portal-thread indirection means
successive pipeline runs across test functions can hit a pyarrow / pandas
Arrow-to-string cast crash on macOS arm64. Running the app on a single
async loop via ASGITransport keeps the whole thing on one thread and
avoids that class of bug.
"""
from __future__ import annotations
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from dte.api.main import app

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config, items):
    """Auto-tag every test in tests/scenarios/ with @pytest.mark.scenario."""
    for item in items:
        if "tests/scenarios" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.scenario)


@pytest_asyncio.fixture
async def client():
    """Async httpx client bound to the FastAPI app via ASGITransport.

    One event loop, one thread — no portal indirection, no cross-thread
    pyarrow crashes.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    """Copy the JSON fixtures into a per-test tmp dir so tests can point
    filesystem sources at them without racing each other."""
    target = tmp_path / "fixtures"
    target.mkdir()
    for f in FIXTURES.glob("*.json"):
        shutil.copy(f, target / f.name)
    return target


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    d = tmp_path / "out"
    d.mkdir()
    return d


class _IdMinter:
    """Mints unique ids per test and stacks them for teardown cleanup."""

    def __init__(self):
        self._prefix = f"scn_{uuid4().hex[:8]}"
        self.pipelines: list[str] = []
        self.destinations: list[str] = []
        self.sources: list[str] = []
        self.connections: list[str] = []
        self.lookups: list[str] = []
        self.eval_sets: list[str] = []

    def __call__(self, kind: str, suffix: str = "") -> str:
        """Mint an id like `scn_ab12cd34_src`. Also records it for teardown."""
        parts = [self._prefix, suffix or kind]
        new_id = "_".join(p for p in parts if p)
        bucket = {
            "pipeline": self.pipelines,
            "destination": self.destinations,
            "source": self.sources,
            "connection": self.connections,
            "lookup": self.lookups,
            "eval_set": self.eval_sets,
        }[kind]
        bucket.append(new_id)
        return new_id


@pytest_asyncio.fixture
async def scenario_ids(client: AsyncClient):
    """Per-test id minter with reverse-dependency-order teardown.

    Yields a callable: `scenario_ids("source", "orders") -> "scn_xxx_orders"`.
    At teardown, deletes ids in pipeline → lookup → destination → source →
    connection order.
    """
    minter = _IdMinter()
    yield minter
    for pid in minter.pipelines:
        await client.delete(f"/api/pipelines/{pid}")
    # Eval sets before sources: examples cascade off the set, and the set
    # points at the source it labels.
    for esid in minter.eval_sets:
        await client.delete(f"/api/eval-sets/{esid}")
    for lid in minter.lookups:
        await client.delete(f"/api/lookup-tables/{lid}")
    for did in minter.destinations:
        await client.delete(f"/api/destinations/{did}")
    for sid in minter.sources:
        await client.delete(f"/api/sources/{sid}")
    for cid in minter.connections:
        if cid == "local_fs":  # pre-seeded; keep
            continue
        await client.delete(f"/api/connections/{cid}")
