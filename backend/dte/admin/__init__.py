"""FastAdmin mount for /admin.

Deviations from plan 023 (task 4):

- Only User / Role / Connection ModelAdmins are registered in this
  first cut — those are the RBAC-critical entities that most benefit
  from a raw-table editor. Pipeline / Source / Destination /
  LookupTable / Run admins can land later without changing this
  wiring; the register calls just get appended.
- FastAdmin's SQLAlchemy provider is async — we build an `async_sessionmaker`
  off the same `DATABASE_URL` (asyncpg driver) the app already uses.
- Login is our own User table: FastAdmin's `authenticate(username, pw)`
  calls into `PostgresUserStore` via a sync session; success requires
  the user to also carry the `user:read` permission so a viewer can't
  wander into the admin UI.
"""
from __future__ import annotations

import os

from fastapi import FastAPI


def _sync_url() -> str:
    url = os.environ["DATABASE_URL"]
    return url.replace("+asyncpg", "")


def _configure_admin_env() -> None:
    """FastAdmin reads its config from env vars. Set the required ones
    before importing fastadmin so its Settings singleton picks them up."""
    os.environ.setdefault("ADMIN_USER_MODEL", "User")
    os.environ.setdefault("ADMIN_USER_MODEL_USERNAME_FIELD", "email")
    # Reuse the JWT secret for admin sessions if a dedicated one isn't set.
    # Prod should set DTE_ADMIN_SECRET_KEY explicitly.
    if "ADMIN_SECRET_KEY" not in os.environ:
        os.environ["ADMIN_SECRET_KEY"] = os.environ.get(
            "DTE_ADMIN_SECRET_KEY", os.environ.get("DTE_JWT_SECRET", "dev-admin-key")
        )
    os.environ.setdefault("ADMIN_SITE_NAME", "DTE Admin")


def mount_admin(app: FastAPI) -> bool:
    """Mount FastAdmin at /admin if `DTE_ADMIN_ENABLED=true`.

    Returns True if mounted, False otherwise. Safe to call even without
    fastadmin installed — the ImportError is swallowed and a warning
    printed so the API keeps working."""
    if os.environ.get("DTE_ADMIN_ENABLED", "").lower() not in ("1", "true", "yes"):
        return False

    _configure_admin_env()

    try:
        from fastadmin import fastapi_app as admin_app
    except ImportError:
        import warnings
        warnings.warn(
            "DTE_ADMIN_ENABLED=true but fastadmin is not installed. "
            "Add `fastadmin` and `python-multipart` to the runtime deps.",
            stacklevel=2,
        )
        return False

    # Register model admins (side-effecting imports register the classes
    # with FastAdmin's internal registry). Do this once, guarded so hot
    # reload doesn't double-register.
    if not getattr(mount_admin, "_registered", False):
        from dte.admin import model_admins  # noqa: F401 — side effects
        mount_admin._registered = True

    app.mount("/admin", admin_app)
    return True
