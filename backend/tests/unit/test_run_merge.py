"""Runs = Airflow dag runs merged with DTE's `run_results` in Python (plan 075),
so DTE's database never needs to see Airflow's `dag_run` table."""
from datetime import datetime, timedelta, timezone

import pytest

from dte.store.postgres import PostgresRunStore, _merge

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _dr(run_id, pid="p1", state="success", minutes=0, conf=None, run_type="manual", start=True):
    t = T0 + timedelta(minutes=minutes)
    return {"run_id": run_id, "dag_id": f"dte__{pid}", "state": state, "queued_at": t,
            "start_date": t if start else None, "end_date": t if state in ("success", "failed") else None,
            "run_type": run_type, "conf": conf or {}}


def _rr(run_id, pid="p1", **kw):
    return {"run_id": run_id, "dag_id": f"dte__{pid}", "pipeline_id": pid, "revision_id": None,
            "status": None, "error": None, "rows_written": None, "location": None, "params": None,
            "quality_checks": None, "sql_query": None, "eval_set_id": None, "labels_version": None,
            "config_digest": None, "sweep_id": None, "scores": None, **kw}


@pytest.mark.parametrize("state,recorded,expected", [
    ("success", None, "completed"),
    ("failed", None, "failed"),
    ("success", "completed_with_warnings", "completed_with_warnings"),
    ("failed", "failed_quality", "failed_quality"),
    ("failed", "failed", "failed"),          # not one of the three the operator owns
    ("running", "completed", "running"),     # the dag run decides until it finishes
    ("queued", None, "pending"),
    (None, None, "pending"),
])
def test_status(state, recorded, expected):
    rr = _rr("r") if recorded is None else _rr("r", status=recorded)
    assert _merge(_dr("r", state=state), rr)["status"] == expected


def test_queued_run_falls_back_to_dag_id_and_conf():
    conf = {"revision_id": "rev1", "eval_set_id": "es1", "sweep_id": "sw1", "context": {"x": 1}}
    m = _merge(_dr("r", pid="abc", state="queued", conf=conf, start=False), None)
    assert m["pipeline_id"] == "abc"
    assert (m["revision_id"], m["eval_set_id"], m["sweep_id"], m["params"]) == ("rev1", "es1", "sw1", {"x": 1})
    assert m["started_at"] == T0  # queued_at stands in for a missing start_date
    assert m["finished_at"] is None
    assert m["quality_checks"] is None and m["scores"] is None


def test_recorded_values_win_over_conf():
    m = _merge(_dr("r", conf={"eval_set_id": "old"}, run_type="scheduled"),
               _rr("r", eval_set_id="new", rows_written=7, scores={"macro_f1": 0.9}))
    assert m["eval_set_id"] == "new"
    assert m["rows_written"] == 7 and m["scores"] == {"macro_f1": 0.9}
    assert m["scheduled"] is True
    assert m["job_id"] is None and m["last_heartbeat_at"] is None


def test_result_from_another_dag_is_ignored():
    m = _merge(_dr("r", pid="a"), _rr("r", pid="b", rows_written=1))
    assert m["rows_written"] is None and m["pipeline_id"] == "a"


class _Store(PostgresRunStore):
    def __init__(self, dag_runs, results):
        calls = self.calls = []

        async def reader(dag_ids=None, run_id=None):
            calls.append((dag_ids, run_id))
            return [d for d in dag_runs
                    if (dag_ids is None or d["dag_id"] in dag_ids) and (run_id is None or d["run_id"] == run_id)]

        super().__init__(session_factory=None, dag_runs=reader)
        self._by_id = {r["run_id"]: r for r in results}

    async def _results(self, ids):
        return {i: self._by_id[i] for i in ids if i in self._by_id}


@pytest.fixture
def store():
    return _Store(
        [_dr("a1", minutes=1), _dr("a2", minutes=2), _dr("a3", state="queued", start=False, minutes=3),
         _dr("b1", pid="b", minutes=4, conf={"eval_set_id": "es"}),
         _dr("s1", pid="root__d1", minutes=6, conf={"sweep_id": "sw"}),
         _dr("s2", pid="root__d2", minutes=5, conf={"sweep_id": "sw"}),
         _dr("x1", pid="rootless", minutes=7, conf={"sweep_id": "other"})],
        [_rr("a1", rows_written=3, quality_checks=[{"passed": True}]),
         _rr("a2", eval_set_id="es", scores={"macro_f1": 0.5})],
    )


async def test_list_for_pipeline_reads_only_its_dag_newest_first(store):
    runs = await store.list_for_pipeline("p1")
    assert [r["id"] for r in runs] == ["a3", "a2", "a1"]
    assert store.calls == [(["dte__p1"], None)]
    assert runs[2]["rows_written"] == 3 and runs[2]["quality"] == {"passed": 1, "failed": 0, "warned": 0}
    assert runs[2]["started_at"] == (T0 + timedelta(minutes=1)).isoformat()
    assert runs[0]["status"] == "pending" and runs[0]["rows_written"] is None


async def test_pagination_and_count(store):
    assert [r["id"] for r in await store.list_for_pipeline("p1", limit=1, offset=1)] == ["a2"]
    assert await store.count_for_pipeline("p1") == 3


async def test_get(store):
    assert (await store.get("a2"))["scores"] == {"macro_f1": 0.5}
    assert store.calls == [(None, "a2")]
    assert await store.get("missing") is None


async def test_eval_set_filter_uses_result_or_conf(store):
    assert [r["id"] for r in await store.list_for_eval_set("es")] == ["b1", "a2"]


async def test_sweep_is_oldest_first(store):
    assert [r["id"] for r in await store.list_for_sweep("sw")] == ["s2", "s1"]


async def test_sweep_runs_for_root_match_variants_only(store):
    assert [r["id"] for r in await store.list_sweep_runs_for_root("root")] == ["s1", "s2"]


def test_run_carries_its_dag_id_for_airflow_links():
    assert _merge(_dr("r", pid="abc", state="queued"), None)["dag_id"] == "dte__abc"
