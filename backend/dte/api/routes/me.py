from __future__ import annotations

from fastapi import APIRouter, Depends

from dte.airflow.auth import get_current_user
from dte.models.user import User

router = APIRouter()


@router.get("/me")
async def me(user: User = Depends(get_current_user)) -> dict:
    """Who the Airflow session is, and what DTE lets them do (for UI gating)."""
    return {"id": user.id, "email": user.email or user.id, "is_active": True,
            "roles": [], "permissions": user.permissions}
