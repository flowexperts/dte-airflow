"""Start / cancel a DTE run by talking to Airflow's public REST API.

The caller's own credentials are forwarded (Bearer header or the `_token`
cookie), so Airflow's auth decides whether they may trigger the DAG.
`capture_auth` is a router-level dependency that stashes them per request.
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextvars import ContextVar

import httpx
from fastapi import HTTPException, Request

_auth: ContextVar[dict[str, str]] = ContextVar("dte_airflow_auth", default={})


def airflow_url() -> str:
    return os.getenv("DTE_AIRFLOW_URL", "http://localhost:8080").rstrip("/")


async def capture_auth(request: Request) -> None:
    token = None
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        token = h[7:]
    token = token or request.cookies.get("_token")
    _auth.set({"Authorization": f"Bearer {token}"} if token else {})


def dag_id_for(pipeline_id: str) -> str:
    return f"dte__{pipeline_id}"


async def _call(method: str, path: str, **kw) -> httpx.Response:
    async with httpx.AsyncClient(timeout=30) as c:
        return await c.request(method, f"{airflow_url()}/api/v2{path}", headers=_auth.get(), **kw)


def revision_tag(revision_id: str) -> str:
    return f"dte-revision:{revision_id}"


async def trigger_dag_run(pipeline_id: str, conf: dict, wait: float = 0) -> str:
    """Create a manual dag run of the pipeline's DAG; returns the run id.
    `wait` > 0 polls for a DAG the dag-processor hasn't parsed yet (a sweep
    saves its variants and triggers them straight away) and, when `conf`
    pins a revision, for the DAG version carrying it — so the run is filed
    under the DAG version it actually executes (plan 068)."""
    run_id = str(uuid.uuid4())
    deadline = time.monotonic() + wait
    if rev := conf.get("revision_id"):
        while True:
            r = await _call("GET", f"/dags/{dag_id_for(pipeline_id)}")
            tags = {t["name"] for t in r.json().get("tags", [])} if r.status_code == 200 else set()
            if revision_tag(rev) in tags or time.monotonic() >= deadline:
                break
            await asyncio.sleep(3)
    while True:
        r = await _call("POST", f"/dags/{dag_id_for(pipeline_id)}/dagRuns",
                        json={"dag_run_id": run_id, "conf": conf, "logical_date": None})
        if r.status_code != 404 or time.monotonic() >= deadline:
            break
        await asyncio.sleep(3)
    if r.status_code == 404:
        raise HTTPException(status_code=409, detail="Pipeline DAG not in Airflow yet — the dag-processor picks up new "
                                                    "pipelines within ~30s. Try again shortly.")
    if r.status_code in (401, 403):
        raise HTTPException(status_code=r.status_code, detail="Airflow refused the trigger")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Airflow error {r.status_code}: {r.text[:300]}")
    return run_id


async def cancel_dag_run(dag_id: str, run_id: str) -> bool:
    r = await _call("PATCH", f"/dags/{dag_id}/dagRuns/{run_id}", json={"state": "failed"})
    return r.status_code < 400
