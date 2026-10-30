"""Engines for DTE's `dte` schema (plans 065, 075).

URL: `DTE_DATABASE_URL`, any Postgres (a dedicated `dte` database is the
recommended setup), else Airflow's `sql_alchemy_conn`. DTE never reads
Airflow's tables through these engines; dag runs come from `dag_runs.py`.
"""
from __future__ import annotations

import os
import re

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine

SEARCH_PATH = "dte,public"
_PG = re.compile(r"^postgres(ql)?(\+\w+)?://")


def _base_url() -> str:
    url = os.getenv("DTE_DATABASE_URL")
    if not url:
        from airflow.configuration import conf

        url = conf.get("database", "sql_alchemy_conn")
    if not _PG.match(url):
        # Airflow 3 blanks its metadata DB URL in DAG parsing and task
        # processes, which is exactly where DTE reads its schema (plan 073).
        raise RuntimeError("DTE needs DTE_DATABASE_URL (a Postgres database for DTE's tables) set on every "
                           "Airflow component; Airflow hides its own URL from DAG parsing and tasks")
    return url


def sync_url() -> str:
    return _PG.sub("postgresql+psycopg2://", _base_url())


def async_url() -> str:
    return _PG.sub("postgresql+asyncpg://", _base_url())


def sync_engine():
    return create_engine(sync_url(), connect_args={"options": f"-csearch_path={SEARCH_PATH}"})


def async_engine():
    return create_async_engine(async_url(), connect_args={"server_settings": {"search_path": SEARCH_PATH}})
