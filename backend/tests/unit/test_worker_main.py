"""Tests for the `python -m dte.worker` entrypoint (plan 046 task 6)."""
from __future__ import annotations

import asyncio


class _FakeOpenContext:
    def __init__(self, app):
        self.app = app

    async def __aenter__(self):
        self.app.opened = True
        return self.app

    async def __aexit__(self, *exc):
        self.app.opened = False
        return False


class _FakeApp:
    tasks = {"execute_run": object()}

    def __init__(self):
        self.opened = False
        self.ran_worker = False

    def open_async(self):
        return _FakeOpenContext(self)

    async def run_worker_async(self, **kwargs):
        assert self.opened, "run_worker_async called before open_async entered"
        # Yield control so the reaper task (spawned alongside this call in
        # _run) gets a chance to start before we return and _run cancels it.
        await asyncio.sleep(0.01)
        self.ran_worker = True


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_run_opens_app_before_running_worker(monkeypatch):
    from dte.worker import __main__ as worker_main

    fake = _FakeApp()
    monkeypatch.setattr(worker_main, "get_app", lambda: fake)
    # The reaper needs a real session factory (DATABASE_URL); stub it so
    # this test stays focused on the app open/run-worker orchestration.
    monkeypatch.setattr("dte.api.deps._session_factory", lambda: object())
    reaper_started = asyncio.Event()

    async def fake_reaper_loop(session_factory):
        reaper_started.set()
        await asyncio.Event().wait()  # never returns on its own — cancelled by _run

    monkeypatch.setattr(worker_main, "run_reaper_loop", fake_reaper_loop)

    _run(worker_main._run())

    assert fake.ran_worker is True
    assert reaper_started.is_set()
    # Context manager exits cleanly — pool is closed again after the run.
    assert fake.opened is False
