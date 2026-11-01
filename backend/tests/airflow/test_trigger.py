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


def test_file_mode_pins_the_file_as_it_is_now(tmp_path, monkeypatch):
    """Plan 090: the DAG is tagged with the file's content hash, so that is
    the revision to pin and wait for — not the DB revision id."""
    from dte.store.files import read_revision

    (tmp_path / "p.yaml").write_text("id: p\nname: P\n")
    monkeypatch.setenv("DTE_PIPELINE_STORE", "file")
    monkeypatch.setenv("DTE_PIPELINES_DIR", str(tmp_path))
    posted = []

    async def _call(method, path, **kw):
        if method == "GET":
            return NS(status_code=200, json=lambda: {"tags": [{"name": f"dte-revision:{rid}"}]})
        posted.append(kw["json"]["conf"])
        return NS(status_code=200, text="")

    rid = read_revision(tmp_path / "p.yaml").id
    monkeypatch.setattr(trig, "_call", _call)
    asyncio.new_event_loop().run_until_complete(trigger_dag_run("p", {"revision_id": "db-uuid"}, wait=60))
    assert posted[0]["revision_id"] == rid
