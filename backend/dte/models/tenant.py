"""Tenant model — two-class SQLModel pattern (mirrors Pipeline).

TenantBase — API/domain fields.
Tenant     — persistence identity, `table=True`.

MVP: one tenant per user. The `tenant_id` on every user-owned entity is
populated from the JWT `tenant` claim at request time.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Text, func
from sqlmodel import Field as SMField
from sqlmodel import SQLModel


class TenantBase(SQLModel):
    """API/domain fields. `id` is required so FastAPI raises 422 on missing."""
    id: str
    name: str


class Tenant(TenantBase, table=True):
    __tablename__ = "tenants"

    id: str = SMField(primary_key=True)  # type: ignore[override]
    name: str = SMField(sa_column=Column(Text, nullable=False))  # type: ignore[override]
    created_at: datetime | None = SMField(
        default=None, sa_column=Column(server_default=func.now())
    )


TenantCreate = TenantBase
