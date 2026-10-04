"""Permission enum + `requires(perm)` FastAPI dependency.

`get_current_user` (Airflow-backed, `dte.airflow.auth`) fills `user.permissions`
from Airflow DAG access; `requires(perm)` checks it.
"""
from __future__ import annotations

from typing import Literal, get_args

from fastapi import Depends, HTTPException

from dte.api.deps import get_current_user
from dte.models.user import User

Permission = Literal[
    "pipeline:read", "pipeline:write", "pipeline:delete", "pipeline:trigger",
    "source:read", "source:write", "source:delete",
    "destination:read", "destination:write", "destination:delete",
    "connection:read", "connection:write", "connection:delete", "connection:test",
    "lookup_table:read", "lookup_table:write", "lookup_table:delete",
    "dashboard:read", "dashboard:write", "dashboard:delete",
    "run:read", "run:delete",
    "eval:read", "eval:write", "eval:delete",
]

ALL_PERMISSIONS: list[str] = list(get_args(Permission))


# Canned permission sets (tests, docs). Live users get theirs from Airflow.
ADMIN_PERMISSIONS: list[str] = list(ALL_PERMISSIONS)
EDITOR_PERMISSIONS: list[str] = [
    p for p in ALL_PERMISSIONS
    if p.endswith(":read") or p.endswith(":write") or p in {"pipeline:trigger", "connection:test"}
]
VIEWER_PERMISSIONS: list[str] = [p for p in ALL_PERMISSIONS if p.endswith(":read")]


def user_has_perm(user: User, perm: str) -> bool:
    return perm in user.permissions


def requires(perm: Permission):
    """FastAPI dependency factory. Attach as
    `dependencies=[Depends(requires("pipeline:read"))]` on individual routes."""
    async def dep(user: User = Depends(get_current_user)) -> User:
        if not user_has_perm(user, perm):
            raise HTTPException(status_code=403, detail=f"missing permission: {perm}")
        return user
    return dep
