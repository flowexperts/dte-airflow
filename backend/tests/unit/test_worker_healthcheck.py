"""The worker's own liveness probe.

The worker shares the API's image and so inherited the API's HTTP
healthcheck, which it can never pass — it serves no HTTP. It reported
`unhealthy` permanently, which is worse than reporting nothing: a column that
is always red teaches everyone to stop reading it.
"""

import asyncio

import pytest

from dte.worker.healthcheck import check, main


@pytest.mark.asyncio
async def test_missing_database_url_is_unhealthy_and_says_so():
    healthy, detail = await check(database_url="")
    assert healthy is False
    assert "DATABASE_URL" in detail


@pytest.mark.asyncio
async def test_unreachable_database_is_unhealthy_with_the_reason():
    """The detail is returned rather than swallowed so it reaches
    `docker inspect`'s health log, which is where anyone debugging looks."""
    healthy, detail = await check(
        database_url="postgresql+asyncpg://nobody:nobody@127.0.0.1:1/none"
    )
    assert healthy is False
    assert detail and "DATABASE_URL" not in detail


@pytest.mark.asyncio
async def test_probe_does_not_leak_a_connection_per_run(monkeypatch):
    """A probe every 15s that holds a pooled connection would eventually pin
    the worker at its connection ceiling — kept there by its own healthcheck."""
    disposed = []

    class FakeConn:
        async def execute(self, *_):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    class FakeEngine:
        def connect(self):
            return FakeConn()

        async def dispose(self):
            disposed.append(True)

    monkeypatch.setattr(
        "sqlalchemy.ext.asyncio.create_async_engine", lambda *a, **k: FakeEngine()
    )
    healthy, _ = await check(database_url="postgresql+asyncpg://x/y")
    assert healthy is True
    assert disposed == [True]


@pytest.mark.asyncio
async def test_a_failing_probe_still_disposes(monkeypatch):
    disposed = []

    class Boom:
        def connect(self):
            raise RuntimeError("no route to host")

        async def dispose(self):
            disposed.append(True)

    monkeypatch.setattr(
        "sqlalchemy.ext.asyncio.create_async_engine", lambda *a, **k: Boom()
    )
    healthy, detail = await check(database_url="postgresql+asyncpg://x/y")
    assert healthy is False
    assert "no route to host" in detail
    assert disposed == [True]


def test_main_exits_nonzero_when_unhealthy(monkeypatch, capsys):
    """Docker reads the exit code, so this is the contract that matters."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    try:
        assert main() == 1
        assert "DATABASE_URL" in capsys.readouterr().out
    finally:
        # `main()` runs `asyncio.run`, which closes the loop and leaves the
        # current-loop slot empty. Several worker tests still reach for
        # `get_event_loop().run_until_complete`, so under a randomised order
        # this test would break them from a distance. Put a usable loop back.
        asyncio.set_event_loop(asyncio.new_event_loop())
