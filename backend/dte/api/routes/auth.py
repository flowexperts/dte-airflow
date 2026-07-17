"""Auth routes — login, register, whoami.

Registration is gated by `DTE_ALLOW_REGISTRATION` — set truthy in dev/
docker-compose to bootstrap the first user. Plan 023 will move user
creation into the admin flow and this env flag can be flipped off in prod.
"""
from __future__ import annotations

import os
import uuid

import jwt as _jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from dte.api.deps import get_current_user, get_user_store
from dte.models.user import User, UserBase
from dte.security.jwt import create_access_token
from dte.security.passwords import hash_password, verify_password
from dte.store.base import UserStore

router = APIRouter()


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class RegisterBody(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserPublic(BaseModel):
    id: str
    email: str
    is_active: bool
    roles: list[str] = []
    permissions: list[str] = []


def _to_public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        roles=sorted(r.id for r in user.roles),
        permissions=sorted(user.permissions),
    )


def _registration_allowed() -> bool:
    return os.getenv("DTE_ALLOW_REGISTRATION", "").lower() in ("1", "true", "yes")


@router.post("/auth/register", response_model=UserPublic, status_code=201)
async def register(body: RegisterBody, users: UserStore = Depends(get_user_store)) -> UserPublic:
    if not _registration_allowed():
        raise HTTPException(status_code=403, detail="Registration is disabled")
    existing = await users.get_by_email(str(body.email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email already registered")
    # First user bootstraps as admin (plan 023). Subsequent users get no
    # role and an existing admin promotes them.
    is_first = (await users.count()) == 0
    new_id = uuid.uuid4().hex
    base = UserBase(id=new_id, email=body.email, is_active=True)
    await users.save(base, password_hash=hash_password(body.password))
    if is_first:
        await users.add_role(new_id, "admin")
    saved = await users.get_by_id(new_id)
    return _to_public(saved)


@router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginBody, users: UserStore = Depends(get_user_store)) -> TokenResponse:
    user = await users.get_by_email(str(body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    token = create_access_token(user_id=user.id, email=user.email)
    return TokenResponse(access_token=token)


@router.get("/auth/me", response_model=UserPublic)
async def me(current: User = Depends(get_current_user)) -> UserPublic:
    return _to_public(current)
