"""Airflow-backed auth for the DTE API (plan 065).

Login, sessions and users are Airflow's. The caller is resolved with Airflow's
own `get_user` (Bearer token or the `_token` cookie the UI sets), and DTE
permissions map onto Airflow DAG access: read -> GET, write -> PUT,
delete -> DELETE, trigger/test -> POST.
"""
from __future__ import annotations

from fastapi import Request

from dte.models.user import User

_METHOD = {"read": "GET", "write": "PUT", "delete": "DELETE", "trigger": "POST", "test": "POST"}


def _resolver():
    from airflow.api_fastapi.app import get_auth_manager
    from airflow.api_fastapi.core_api.security import get_user

    return get_auth_manager, get_user


async def get_current_user(request: Request) -> User:
    """FastAPI dependency. Airflow imports are lazy so DTE's API still
    imports (and tests override this) outside an Airflow environment."""
    from dte.security.permissions import ALL_PERMISSIONS

    get_auth_manager, get_user = _resolver()
    # Positional: Airflow 3.3 renamed `oauth_token` to `_oauth_token` (unused
    # at runtime); the order (request, oauth token, bearer) is stable.
    user = await get_user(request, None, await _bearer(request))
    mgr = get_auth_manager()
    allowed = {m: mgr.is_authorized_dag(method=m, user=user) for m in set(_METHOD.values())}
    perms = [p for p in ALL_PERMISSIONS if allowed[_METHOD[p.split(":")[1]]]]
    return User(id=str(user.get_id()), email=user.get_name(), permissions=perms)


async def _bearer(request: Request):
    from fastapi.security import HTTPBearer

    return await HTTPBearer(auto_error=False)(request)
