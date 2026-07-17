"""FastAdmin ModelAdmins for the RBAC-critical entities.

Only User / Role / UserRoleLink are registered. Connection is *not* —
the app UI at /connections owns the safe editing path (creds go through
the SecretResolver), and a raw table editor would just create two ways
to change the same row with different guardrails.
"""
from __future__ import annotations

import os
import uuid as _uuid
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select

from fastadmin import SqlAlchemyModelAdmin, WidgetType, register

from dte.models.user import Role, User, UserRoleLink
from dte.security.passwords import hash_password, verify_password
from dte.security.permissions import ALL_PERMISSIONS


def _make_sessionmaker():
    # FastAdmin's SQLAlchemy provider is async — reuse the same asyncpg URL
    # the app uses. Keeping a separate engine to avoid mixing sessions.
    engine = create_async_engine(os.environ["DATABASE_URL"])
    return async_sessionmaker(engine, expire_on_commit=False)


_sessionmaker = _make_sessionmaker()


@register(User, sqlalchemy_sessionmaker=_sessionmaker)
class UserAdmin(SqlAlchemyModelAdmin):
    """Admin for our User table. Login uses email + password against
    the same password_hash that the API uses; only users with
    `user:read` permission are allowed into the admin UI."""

    list_display = ("id", "email", "is_active", "created_at")
    list_display_links = ("id", "email")

    # Render `password_hash` as a masked password field so the admin
    # can set/change passwords from the UI. `orm_save_obj` hashes
    # whatever plaintext gets submitted before insert/update.
    formfield_overrides = {  # type: ignore[assignment]
        "password_hash": (WidgetType.PasswordInput, {"required": True}),
    }

    async def orm_save_obj(self, id, payload):  # type: ignore[override]
        # The users PK has no DB default (our IDs are uuid4().hex generated
        # in app code). Inject one on add so the insert doesn't NULL-violate.
        if id is None and not payload.get("id"):
            payload = {**payload, "id": _uuid.uuid4().hex}
        # Password gets hashed by change_password() below — but on add the
        # base save_model writes it plaintext first. Hash it here so we
        # never touch the column with plaintext.
        raw_pw = payload.get("password_hash")
        if raw_pw and not raw_pw.startswith("$2"):
            payload = {**payload, "password_hash": hash_password(raw_pw)}
        return await super().orm_save_obj(id, payload)

    async def change_password(self, id, password):  # type: ignore[override]
        # FastAdmin auto-calls this after save whenever a PasswordInput
        # field is present. Also drives POST /admin/api/change-password.
        hashed = hash_password(password)
        # Reuse the parent's orm_save_obj so we go through the same code
        # path (audit, updated_at trigger, etc.).
        pk = id.hex if isinstance(id, UUID) else id
        await SqlAlchemyModelAdmin.orm_save_obj(self, pk, {"password_hash": hashed})

    async def get_obj(self, id):  # type: ignore[override]
        # FastAdmin's sign_in serialises the user id as `str(UUID)` (dashed
        # hex). Our DB stores `uuid4().hex` (undashed). Normalise both forms
        # to the hex we actually persist before hitting the ORM.
        if isinstance(id, str) and "-" in id:
            try:
                id = UUID(id).hex
            except ValueError:
                pass
        elif isinstance(id, UUID):
            id = id.hex
        return await super().get_obj(id)

    async def authenticate(self, username: str, password: str):  # type: ignore[override]
        # username here is the value of the field named by
        # ADMIN_USER_MODEL_USERNAME_FIELD ("email").
        async with _sessionmaker() as s:
            user = (await s.execute(select(User).where(User.email == username))).scalars().first()
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None

        # Also require user:read — otherwise a viewer with the login
        # form URL could poke around.
        async with _sessionmaker() as s:
            role_rows = (await s.execute(
                select(Role)
                .join(UserRoleLink, UserRoleLink.role_id == Role.id)
                .where(UserRoleLink.user_id == user.id)
            )).scalars().all()
        if not any("user:read" in (r.permissions or []) for r in role_rows):
            return None

        # FastAdmin's sign_in accepts only int or UUID (not plain str). Our
        # ids are `uuid4().hex` — coerce back to a real UUID; get_obj below
        # re-normalises the dashed form back to hex for the ORM lookup.
        try:
            return UUID(user.id)
        except (ValueError, TypeError):
            return None


@register(Role, sqlalchemy_sessionmaker=_sessionmaker)
class RoleAdmin(SqlAlchemyModelAdmin):
    """Role editor. `permissions` is a Postgres TEXT[] — FastAdmin can't
    infer a multi-select from that, so we hand it the closed set from
    the `Permission` enum. Extending the enum (e.g. adding a new
    resource) auto-populates this dropdown."""

    list_display = ("id", "name", "permissions")
    list_display_links = ("id", "name")

    formfield_overrides = {  # type: ignore[assignment]
        "permissions": (
            WidgetType.Select,
            {
                "mode": "multiple",
                "options": [{"label": p, "value": p} for p in ALL_PERMISSIONS],
            },
        ),
    }


@register(UserRoleLink, sqlalchemy_sessionmaker=_sessionmaker)
class UserRoleLinkAdmin(SqlAlchemyModelAdmin):
    list_display = ("user_id", "role_id")
