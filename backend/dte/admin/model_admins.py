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

    list_display = ("id", "email", "is_active")
    list_display_links = ("id", "email")
    # Timestamps are set by the DB — hide them from add/edit forms and
    # from the list. If we ever need to show them in the list, add a
    # dedicated read-only column later.
    exclude = ("created_at", "updated_at")

    def get_model_fields_with_widget_types(self, with_m2m=None):  # type: ignore[override]
        """Append a synthetic `roles` multi-select to the User form so
        the admin can grant/revoke roles without touching a junction
        table. It maps to UserRoleLink rows on save."""
        from fastadmin.models.schemas import ModelFieldWidgetSchema

        fields = super().get_model_fields_with_widget_types(with_m2m=with_m2m)
        # M2M variant returns only m2m fields; we only add ours when
        # non-m2m fields are being asked for.
        if with_m2m:
            return fields
        roles_field = ModelFieldWidgetSchema(
            name="roles",
            column_name="roles",
            is_m2m=False,
            is_pk=False,
            is_immutable=False,
            form_widget_type=WidgetType.AsyncSelect,
            form_widget_props={
                "required": False,
                "disabled": False,
                "readOnly": False,
                "mode": "multiple",
                "parentModel": "Role",
                "idField": "id",
                "labelFields": ("__str__", "id"),
            },
            filter_widget_type=WidgetType.Input,
            filter_widget_props={},
        )
        return list(fields) + [roles_field]

    # Render `password_hash` as a masked password field so the admin
    # can set/change passwords from the UI. `orm_save_obj` hashes
    # whatever plaintext gets submitted before insert/update.
    # `label: "Password"` piggybacks on Ant Design's Form.Item — if
    # FastAdmin's frontend spreads form_widget_props to the item, this
    # renames the field; if it doesn't, the fallback name "password_hash"
    # is at least consistent with the wire.
    formfield_overrides = {  # type: ignore[assignment]
        "password_hash": (
            WidgetType.PasswordInput,
            {"required": True, "label": "Password"},
        ),
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
        # Pull `roles` out of the payload so it doesn't reach the User INSERT.
        # We reconcile UserRoleLink rows after save.
        role_ids = payload.pop("roles", None) if isinstance(payload, dict) else None
        obj = await super().orm_save_obj(id, payload)
        if role_ids is not None:
            pk = payload.get("id") or (obj.id if hasattr(obj, "id") else id)
            await self._sync_roles(pk, role_ids)
        return obj

    async def _sync_roles(self, user_id, role_ids):
        """Replace the user's role assignments with `role_ids`."""
        role_ids = [str(r) for r in (role_ids or [])]
        async with _sessionmaker() as s:
            existing = (await s.execute(
                select(UserRoleLink).where(UserRoleLink.user_id == user_id)
            )).scalars().all()
            existing_role_ids = {link.role_id for link in existing}
            wanted = set(role_ids)
            for link in existing:
                if link.role_id not in wanted:
                    await s.delete(link)
            for rid in wanted - existing_role_ids:
                s.add(UserRoleLink(user_id=user_id, role_id=rid))
            await s.commit()

    async def serialize_obj(self, obj):  # type: ignore[override]
        """Include the user's current role ids so the edit form pre-selects
        them in the AsyncSelect."""
        data = await super().serialize_obj(obj)
        async with _sessionmaker() as s:
            links = (await s.execute(
                select(UserRoleLink).where(UserRoleLink.user_id == obj.id)
            )).scalars().all()
        data["roles"] = [link.role_id for link in links]
        return data

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


# NOTE: UserRoleLink is not registered as its own admin page. The composite
# PK (user_id, role_id) breaks FastAdmin's `session.get(cls, id)` calls, and
# a raw junction table is a poor UX anyway. Role assignment is exposed as a
# multi-select on the User admin below (see UserAdmin._sync_roles).
