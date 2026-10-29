"""Engines for DTE's `dte` schema inside Airflow's metadata DB (plan 065).

URL: `DATABASE_URL` (as before), else Airflow's `sql_alchemy_conn`. Airflow's
own tables stay reachable on the search_path so run reads can join `dag_run`.
"""
from __future__ import annotations

import os
import re

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine

SEARCH_PATH = "dte,public"
_PG = re.compile(r"^postgres(ql)?(\+\w+)?://")


def _base_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        from airflow.configuration import conf

        url = conf.get("database", "sql_alchemy_conn")
    if not _PG.match(url):
        # Airflow 3 blanks its metadata DB URL in DAG parsing and task
        # processes, which is exactly where DTE reads its schema (plan 073).
        raise RuntimeError("DTE needs DATABASE_URL (the Postgres metadata DB) set on every Airflow "
                           "component; Airflow hides its own URL from DAG parsing and tasks")
    return url


def sync_url() -> str:
    return _PG.sub("postgresql+psycopg2://", _base_url())


def async_url() -> str:
    return _PG.sub("postgresql+asyncpg://", _base_url())


def sync_engine():
    return create_engine(sync_url(), connect_args={"options": f"-csearch_path={SEARCH_PATH}"})


def async_engine():
    return create_async_engine(async_url(), connect_args={"server_settings": {"search_path": SEARCH_PATH}})
