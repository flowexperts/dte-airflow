"""Store wiring for FastAPI routes.

Postgres-only: `DATABASE_URL` must be set. There is no in-memory
fallback in production code — tests inject fakes via
`app.dependency_overrides[get_pipeline_store] = lambda: FakePipelineStore()`
(see `tests/fakes.py`).
"""
from __future__ import annotations

import os
from functools import lru_cache

import jwt as _jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from dte.models.user import User
from dte.security.jwt import decode_access_token
from dte.store.base import UserStore
from dte.store.postgres import (
    PostgresConnectionStore,
    PostgresDestinationStore,
    PostgresLookupTableStore,
    PostgresPipelineRevisionStore,
    PostgresPipelineStore,
    PostgresRoleStore,
    PostgresRunEventStore,
    PostgresRunStore,
    PostgresSourceStore,
    PostgresUserStore,
)


@lru_cache(maxsize=1)
def _session_factory():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. dte requires Postgres in every "
            "environment; tests inject stores via app.dependency_overrides."
        )
    engine = create_async_engine(url)
    return async_sessionmaker(engine, expire_on_commit=False)


def get_pipeline_store():
    return PostgresPipelineStore(_session_factory())


def get_pipeline_revision_store():
    return PostgresPipelineRevisionStore(_session_factory())


def get_run_store():
    return PostgresRunStore(_session_factory())


def get_run_event_store():
    return PostgresRunEventStore(_session_factory())


def get_source_store():
    return PostgresSourceStore(_session_factory())


def get_destination_store():
    return PostgresDestinationStore(_session_factory())


def get_connection_store():
    return PostgresConnectionStore(_session_factory())


def get_user_store():
    return PostgresUserStore(_session_factory())


def get_role_store():
    return PostgresRoleStore(_session_factory())


def get_lookup_table_store():
    return PostgresLookupTableStore(_session_factory())


# Swagger UI Authorize button wires to this URL.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=True)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    users: UserStore = Depends(get_user_store),
) -> User:
    creds_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
    except _jwt.PyJWTError:
        raise creds_error
    user_id = payload.get("sub")
    if not user_id:
        raise creds_error
    user = await users.get_by_id(user_id)
    if user is None or not user.is_active:
        raise creds_error
    return user
