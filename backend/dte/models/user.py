"""User model — two-class SQLModel pattern (mirrors Pipeline).

UserBase  — API/domain fields + Pydantic validators. Used as the
            POST/PUT body type in routes (task 2). `id` required here
            so FastAPI raises 422 when the client omits it.

User      — persistence identity. `table=True` so SQLModel registers
            the ORM mapping. Adds `password_hash` (never returned on
            the wire), timestamps, and the primary-key override.

UserCreate — alias for UserBase kept for symmetry; adds `password`
             field (plaintext at the edge; hashed before insert).

SQLModel 0.0.39 gotcha: `table=True` skips Pydantic validators, and
`Literal[...]` on a table class breaks the metaclass. This model
avoids both issues — no Literal on the table class, no post-hydration
narrowing needed.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr
from sqlalchemy import Column, Text, Boolean, func
from sqlmodel import Field as SMField, SQLModel


class UserBase(SQLModel):
    """API/domain fields. Validated at the edge by Pydantic."""

    id: str
    email: EmailStr = SMField(
        sa_column=Column(Text, unique=True, nullable=False, index=True)
    )
    is_active: bool = True


class User(UserBase, table=True):
    __tablename__ = "users"

    # Primary key override (required by SQLModel table=True pattern).
    id: str = SMField(primary_key=True)  # type: ignore[override]

    # Override email without the sa_column so the table class only
    # declares the plain column (the index/unique are on the Base).
    email: str = SMField(sa_column=Column(Text, unique=True, nullable=False, index=True))  # type: ignore[override]

    # Override is_active to map to a real boolean column.
    is_active: bool = SMField(  # type: ignore[override]
        default=True, sa_column=Column(Boolean, nullable=False, server_default="true")
    )

    # Password hash — never returned on the wire; only stored in this class.
    password_hash: str = SMField(sa_column=Column(Text, nullable=False))

    created_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now()),
    )
    updated_at: datetime | None = SMField(
        default=None,
        sa_column=Column(server_default=func.now(), onupdate=func.now()),
    )


class UserCreate(UserBase):
    """Used at the registration endpoint (task 2). Carries plaintext
    password — the route must hash it before calling UserStore.save."""

    password: str


# Back-compat alias.
UserCreateBase = UserBase
