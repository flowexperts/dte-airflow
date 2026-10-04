"""The authenticated caller. Identity and login live in Airflow (plan 065);
this is only what routes need: an id and the permissions `requires` checks."""
from __future__ import annotations

from pydantic import BaseModel


class User(BaseModel):
    id: str
    email: str | None = None
    is_active: bool = True
    permissions: list[str] = []
