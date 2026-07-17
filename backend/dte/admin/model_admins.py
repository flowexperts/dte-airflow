"""FastAdmin ModelAdmins for the RBAC-critical entities.

Uses a **sync** SQLAlchemy engine — FastAdmin's provider is not async.
Kept as a separate engine from the app's async one; they don't share
sessions and don't need to.
"""
from __future__ import annotations

import asyncio
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from fastadmin import SqlAlchemyModelAdmin, register

from dte.models.pipeline import Connection
from dte.models.user import Role, User, UserRoleLink
from dte.security.passwords import verify_password


def _make_sessionmaker():
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    engine = create_engine(url, future=True)
    return sessionmaker(engine, expire_on_commit=False)


_sessionmaker = _make_sessionmaker()


@register(User, sqlalchemy_sessionmaker=_sessionmaker)
class UserAdmin(SqlAlchemyModelAdmin):
    """Admin for our User table. Login uses email + password against
    the same password_hash that the API uses; only users with
    `user:read` permission are allowed into the admin UI."""

    list_display = ("id", "email", "is_active", "created_at")
    list_display_links = ("id", "email")
    exclude = ("password_hash",)  # never show password hash

    async def authenticate(self, username: str, password: str):  # type: ignore[override]
        # username here is the value of the field named by
        # ADMIN_USER_MODEL_USERNAME_FIELD ("email").
        def _lookup():
            with _sessionmaker() as s:
                return s.query(User).filter(User.email == username).first()

        user = await asyncio.get_event_loop().run_in_executor(None, _lookup)
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None

        # Also require user:read — otherwise a viewer with the login
        # form URL could poke around.
        def _has_admin_perm():
            with _sessionmaker() as s:
                stmt = (
                    s.query(Role)
                    .join(UserRoleLink, UserRoleLink.role_id == Role.id)
                    .filter(UserRoleLink.user_id == user.id)
                )
                for r in stmt.all():
                    if "user:read" in (r.permissions or []):
                        return True
            return False

        if not await asyncio.get_event_loop().run_in_executor(None, _has_admin_perm):
            return None

        return user.id


@register(Role, sqlalchemy_sessionmaker=_sessionmaker)
class RoleAdmin(SqlAlchemyModelAdmin):
    list_display = ("id", "name", "permissions")
    list_display_links = ("id", "name")


@register(UserRoleLink, sqlalchemy_sessionmaker=_sessionmaker)
class UserRoleLinkAdmin(SqlAlchemyModelAdmin):
    list_display = ("user_id", "role_id")


@register(Connection, sqlalchemy_sessionmaker=_sessionmaker)
class ConnectionAdmin(SqlAlchemyModelAdmin):
    """Credentials never surface in the admin — editing them here would
    bypass EncryptedJSON. Both the logical `credentials` field and the
    physical `credentials_encrypted` column are excluded."""

    list_display = ("id", "connection_type", "created_at")
    list_display_links = ("id",)
    exclude = ("credentials", "credentials_encrypted")
