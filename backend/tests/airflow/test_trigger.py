"""A run pinned to a revision waits for the DAG version carrying it (plan 068)."""
import asyncio
from types import SimpleNamespace as NS

import dte.airflow.trigger as trig
from dte.airflow.trigger import trigger_dag_run  # the real one; conftest patches the module attr


def test_waits_for_the_revision_tag(monkeypatch):
    calls, tags = [], [["dte", "dte-revision:old"], ["dte", "dte-revision:new"]]

    async def _call(method, path, **kw):
        calls.append(method)
        if method == "GET":
            return NS(status_code=200, json=lambda: {"tags": [{"name": t} for t in tags.pop(0)]})
        return NS(status_code=200, text="")

    async def _sleep(_):
        pass

    monkeypatch.setattr(trig, "_call", _call)
    monkeypatch.setattr(trig.asyncio, "sleep", _sleep)
    asyncio.new_event_loop().run_until_complete(trigger_dag_run("p", {"revision_id": "new"}, wait=60))
    assert calls == ["GET", "GET", "POST"]
