"""User + Role models — two-class SQLModel pattern (mirrors Pipeline).

UserBase   — API/domain fields + Pydantic validators. Bound to POST/PUT
             bodies at the routes.
User       — persistence identity. `table=True`.
RoleBase / Role
           — the RBAC role. `permissions` is a `TEXT[]` on Postgres.
UserRoleLink
           — many-to-many join. Composite (user_id, role_id) PK.

`User.roles` is a plain Python list attached by the store after fetch
(`narrow_roles(...)`), not a SQLAlchemy relationship. SQLModel 0.0.39 +
async eager-loading is too fiddly for what we need; the store just does
a second SELECT.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr
from sqlalchemy import ARRAY, Column, Text, Boolean, func
from sqlmodel import Field as SMField, SQLModel


# ── Role ─────────────────────────────────────────────────────────────────────

class RoleBase(SQLModel):
    id: str
    name: str
    permissions: list[str] = []


class Role(RoleBase, table=True):
    __tablename__ = "roles"

    id: str = SMField(primary_key=True)  # type: ignore[override]
    name: str = SMField(sa_column=Column(Text, unique=True, nullable=False))  # type: ignore[override]
    permissions: list[str] = SMField(  # type: ignore[override]
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"),
    )

    created_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now()),
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now(), onupdate=func.now()),
    )

    def __str__(self) -> str:
        return self.name


class UserRoleLink(SQLModel, table=True):
    __tablename__ = "user_roles"

    user_id: str = SMField(foreign_key="users.id", primary_key=True)
    role_id: str = SMField(foreign_key="roles.id", primary_key=True)


# ── User ─────────────────────────────────────────────────────────────────────

class UserBase(SQLModel):
    """API/domain fields. Validated at the edge by Pydantic."""

    id: str
    email: EmailStr = SMField(
        sa_column=Column(Text, unique=True, nullable=False, index=True)
    )
    is_active: bool = True


class User(UserBase, table=True):
    __tablename__ = "users"

    id: str = SMField(primary_key=True)  # type: ignore[override]
    email: str = SMField(sa_column=Column(Text, unique=True, nullable=False, index=True))  # type: ignore[override]
    is_active: bool = SMField(  # type: ignore[override]
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )
    password_hash: str = SMField(sa_column=Column(Text, nullable=False))

    created_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now()),
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now(), onupdate=func.now()),
    )

    def __str__(self) -> str:
        return self.email

    def narrow_roles(self, roles: list[Role]) -> None:
        """Attach roles fetched by the store. Not a mapped column so SA
        hydration ignores it (mirrors `Destination.narrow_config`)."""
        object.__setattr__(self, "_roles", list(roles))

    @property
    def roles(self) -> list[Role]:
        return getattr(self, "_roles", [])

    @property
    def permissions(self) -> set[str]:
        out: set[str] = set()
        for r in self.roles:
            out.update(r.permissions)
        return out


class UserCreate(UserBase):
    password: str


UserCreateBase = UserBase
