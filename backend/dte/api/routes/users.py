"""User + role management. Gated by `user:*` permissions.

Admin-only surface — the frontend won't render a management page until
plan 023's UI polish, but the API is available for scripting and for
FastAdmin (task 4) to reuse.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from dte.api.deps import get_role_store, get_user_store
from dte.api.routes.auth import UserPublic, _to_public
from dte.models.user import UserBase
from dte.security.passwords import hash_password
from dte.security.permissions import requires
from dte.store.base import RoleStore, UserStore

router = APIRouter()


class CreateUserBody(BaseModel):
    email: EmailStr
    password: str


class AssignRoleBody(BaseModel):
    role_id: str


class RolePublic(BaseModel):
    id: str
    name: str
    permissions: list[str]


@router.get("/users", dependencies=[Depends(requires("user:read"))])
async def list_users(
    limit: int = 50,
    offset: int = 0,
    users: UserStore = Depends(get_user_store),
) -> list[UserPublic]:
    rows = await users.list(limit=limit, offset=offset)
    return [_to_public(u) for u in rows]


@router.get("/users/{user_id}", dependencies=[Depends(requires("user:read"))])
async def get_user(user_id: str, users: UserStore = Depends(get_user_store)) -> UserPublic:
    u = await users.get_by_id(user_id)
    if u is None:
        raise HTTPException(status_code=404, detail="User not found")
    return _to_public(u)


@router.post("/users", status_code=201, dependencies=[Depends(requires("user:write"))])
async def create_user(
    body: CreateUserBody,
    users: UserStore = Depends(get_user_store),
) -> UserPublic:
    if await users.get_by_email(str(body.email)) is not None:
        raise HTTPException(status_code=409, detail="Email already registered")
    new_id = uuid.uuid4().hex
    base = UserBase(id=new_id, email=body.email, is_active=True)
    await users.save(base, password_hash=hash_password(body.password))
    saved = await users.get_by_id(new_id)
    return _to_public(saved)


@router.delete("/users/{user_id}", status_code=204, dependencies=[Depends(requires("user:delete"))])
async def delete_user(user_id: str, users: UserStore = Depends(get_user_store)):
    if not await users.delete(user_id):
        raise HTTPException(status_code=404, detail="User not found")


@router.post("/users/{user_id}/roles", status_code=201, dependencies=[Depends(requires("user:write"))])
async def assign_role(
    user_id: str,
    body: AssignRoleBody,
    users: UserStore = Depends(get_user_store),
    roles: RoleStore = Depends(get_role_store),
) -> UserPublic:
    if await users.get_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if await roles.get(body.role_id) is None:
        raise HTTPException(status_code=422, detail=f"role_id '{body.role_id}' not found")
    await users.add_role(user_id, body.role_id)
    return _to_public(await users.get_by_id(user_id))


@router.delete(
    "/users/{user_id}/roles/{role_id}",
    status_code=204,
    dependencies=[Depends(requires("user:write"))],
)
async def revoke_role(
    user_id: str,
    role_id: str,
    users: UserStore = Depends(get_user_store),
):
    if await users.get_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not await users.remove_role(user_id, role_id):
        raise HTTPException(status_code=404, detail="Role not assigned to user")


@router.get("/roles", dependencies=[Depends(requires("user:read"))])
async def list_roles(roles: RoleStore = Depends(get_role_store)) -> list[RolePublic]:
    return [RolePublic(id=r.id, name=r.name, permissions=list(r.permissions)) for r in await roles.list()]
