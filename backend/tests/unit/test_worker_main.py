"""Tests for the `python -m dte.worker` entrypoint (plan 046 task 6)."""
from __future__ import annotations

import asyncio

import pytest


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
        self.ran_worker = True


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_run_opens_app_before_running_worker(monkeypatch):
    from dte.worker import __main__ as worker_main

    fake = _FakeApp()
    monkeypatch.setattr(worker_main, "get_app", lambda: fake)

    _run(worker_main._run())

    assert fake.ran_worker is True
    # Context manager exits cleanly — pool is closed again after the run.
    assert fake.opened is False
