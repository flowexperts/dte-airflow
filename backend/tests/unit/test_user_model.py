"""Unit tests for user model, password helpers, and FakeUserStore.

TDD: these tests are written before the implementation exists so that
running them first gives a clean set of failures.
"""
from __future__ import annotations

import pytest


# ── Password helper tests ────────────────────────────────────────────────────

def test_hash_password_returns_string():
    from dte.security.passwords import hash_password
    h = hash_password("secret123")
    assert isinstance(h, str)
    assert len(h) > 20


def test_hash_password_is_not_plaintext():
    from dte.security.passwords import hash_password
    h = hash_password("secret123")
    assert h != "secret123"


def test_verify_password_correct():
    from dte.security.passwords import hash_password, verify_password
    h = hash_password("mypassword")
    assert verify_password("mypassword", h) is True


def test_verify_password_wrong():
    from dte.security.passwords import hash_password, verify_password
    h = hash_password("mypassword")
    assert verify_password("wrongpass", h) is False


def test_hash_password_different_salts():
    """Each call must produce a unique hash (bcrypt salts per call)."""
    from dte.security.passwords import hash_password
    h1 = hash_password("same")
    h2 = hash_password("same")
    assert h1 != h2


# ── UserBase / User model tests ──────────────────────────────────────────────

def test_userbase_requires_email():
    from pydantic import ValidationError
    from dte.models.user import UserBase
    with pytest.raises(ValidationError):
        UserBase(id="u1")  # no email


def test_userbase_validates_email_format():
    from pydantic import ValidationError
    from dte.models.user import UserBase
    with pytest.raises(ValidationError):
        UserBase(id="u1", email="not-an-email")


def test_userbase_valid():
    from dte.models.user import UserBase
    u = UserBase(id="u1", email="alice@example.com")
    assert u.email == "alice@example.com"
    assert u.is_active is True


def test_usercreate_has_password_field():
    from dte.models.user import UserCreate
    uc = UserCreate(id="u2", email="bob@example.com", password="pw")
    assert uc.password == "pw"


# ── FakeUserStore tests ──────────────────────────────────────────────────────

pytestmark_store = pytest.mark.asyncio


async def test_fake_user_store_save_and_get_by_id():
    from tests.fakes import FakeUserStore
    from dte.models.user import UserBase
    store = FakeUserStore()
    u = UserBase(id="uid1", email="alice@example.com")
    await store.save(u, password_hash="hashed")
    result = await store.get_by_id("uid1")
    assert result is not None
    assert result.id == "uid1"
    assert result.email == "alice@example.com"
    assert result.password_hash == "hashed"


async def test_fake_user_store_get_by_email():
    from tests.fakes import FakeUserStore
    from dte.models.user import UserBase
    store = FakeUserStore()
    await store.save(UserBase(id="uid2", email="bob@example.com"), password_hash="h2")
    result = await store.get_by_email("bob@example.com")
    assert result is not None
    assert result.id == "uid2"


async def test_fake_user_store_get_by_email_missing_returns_none():
    from tests.fakes import FakeUserStore
    store = FakeUserStore()
    result = await store.get_by_email("nobody@example.com")
    assert result is None


async def test_fake_user_store_get_by_id_missing_returns_none():
    from tests.fakes import FakeUserStore
    store = FakeUserStore()
    result = await store.get_by_id("no-such-id")
    assert result is None


async def test_fake_user_store_list():
    from tests.fakes import FakeUserStore
    from dte.models.user import UserBase
    store = FakeUserStore()
    await store.save(UserBase(id="u-a", email="a@x.com"), password_hash="ha")
    await store.save(UserBase(id="u-b", email="b@x.com"), password_hash="hb")
    users = await store.list()
    assert len(users) == 2


async def test_fake_user_store_delete():
    from tests.fakes import FakeUserStore
    from dte.models.user import UserBase
    store = FakeUserStore()
    await store.save(UserBase(id="u-del", email="del@x.com"), password_hash="hd")
    deleted = await store.delete("u-del")
    assert deleted is True
    assert await store.get_by_id("u-del") is None


async def test_fake_user_store_delete_missing_returns_false():
    from tests.fakes import FakeUserStore
    store = FakeUserStore()
    deleted = await store.delete("ghost")
    assert deleted is False


async def test_fake_user_store_email_uniqueness_on_update():
    """Re-saving with same id overwrites; email must stay unique."""
    from tests.fakes import FakeUserStore
    from dte.models.user import UserBase
    store = FakeUserStore()
    await store.save(UserBase(id="u-upd", email="orig@x.com"), password_hash="h1")
    # Update email on same id
    await store.save(UserBase(id="u-upd", email="new@x.com"), password_hash="h2")
    result = await store.get_by_id("u-upd")
    assert result.email == "new@x.com"
    assert result.password_hash == "h2"
    # Only one user
    all_users = await store.list()
    assert len(all_users) == 1


async def test_fake_user_store_timestamps_set_on_save():
    from tests.fakes import FakeUserStore
    from dte.models.user import UserBase
    store = FakeUserStore()
    await store.save(UserBase(id="u-ts", email="ts@x.com"), password_hash="hts")
    result = await store.get_by_id("u-ts")
    assert result.created_at is not None
    assert result.updated_at is not None


async def test_fake_user_store_created_at_stable_on_update():
    """created_at must not change on re-save."""
    from tests.fakes import FakeUserStore
    from dte.models.user import UserBase
    store = FakeUserStore()
    await store.save(UserBase(id="u-stable", email="st@x.com"), password_hash="h1")
    first = await store.get_by_id("u-stable")
    created_at_first = first.created_at

    await store.save(UserBase(id="u-stable", email="st2@x.com"), password_hash="h2")
    second = await store.get_by_id("u-stable")
    assert second.created_at == created_at_first
