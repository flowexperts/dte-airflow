import os
import pytest
from cryptography.fernet import Fernet

from dte.secrets import get_secret_resolver
from dte.secrets.env import EnvSecretResolver
from dte.secrets.fernet import FernetSecretResolver


def test_env_resolver_roundtrip_literal():
    r = EnvSecretResolver()
    payload = {"user": "alice", "region": "us-east-1"}
    assert r.decrypt(r.encrypt(payload)) == payload


def test_env_resolver_resolves_env_ref(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "s3cret")
    r = EnvSecretResolver()
    plaintext = {"aws_access_key_id": "AKIA...", "aws_secret_access_key": {"env": "MY_SECRET"}}
    decrypted = r.decrypt(r.encrypt(plaintext))
    assert decrypted["aws_secret_access_key"] == "s3cret"


def test_env_resolver_missing_env_var_raises(monkeypatch):
    monkeypatch.delenv("DEFINITELY_NOT_SET", raising=False)
    r = EnvSecretResolver()
    with pytest.raises(KeyError):
        r.decrypt(r.encrypt({"k": {"env": "DEFINITELY_NOT_SET"}}))


def test_env_resolver_recurses_nested_dicts_and_lists(monkeypatch):
    monkeypatch.setenv("A", "aa")
    monkeypatch.setenv("B", "bb")
    r = EnvSecretResolver()
    plaintext = {"nested": {"x": {"env": "A"}, "arr": [{"env": "B"}, "literal"]}}
    got = r.decrypt(r.encrypt(plaintext))
    assert got == {"nested": {"x": "aa", "arr": ["bb", "literal"]}}


def test_fernet_resolver_roundtrip():
    r = FernetSecretResolver(Fernet.generate_key())
    payload = {"connection_url": "postgres://user:pw@host/db"}
    ciphertext = r.encrypt(payload)
    assert isinstance(ciphertext, bytes)
    # A different key must not decrypt the same ciphertext.
    other = FernetSecretResolver(Fernet.generate_key())
    with pytest.raises(Exception):  # cryptography.fernet.InvalidToken
        other.decrypt(ciphertext)
    assert r.decrypt(ciphertext) == payload


def test_factory_picks_fernet_when_key_set(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("DTE_SECRETS_KEY", key)
    monkeypatch.delenv("DTE_SECRETS_BACKEND", raising=False)
    import dte.secrets as mod
    monkeypatch.setattr(mod, "_resolver", None)
    resolver = get_secret_resolver()
    assert isinstance(resolver, FernetSecretResolver)


def test_factory_defaults_to_env(monkeypatch):
    monkeypatch.delenv("DTE_SECRETS_KEY", raising=False)
    monkeypatch.delenv("DTE_SECRETS_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import dte.secrets as mod
    monkeypatch.setattr(mod, "_resolver", None)
    assert isinstance(get_secret_resolver(), EnvSecretResolver)


def test_factory_override_forces_env(monkeypatch):
    monkeypatch.setenv("DTE_SECRETS_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DTE_SECRETS_BACKEND", "env")
    import dte.secrets as mod
    monkeypatch.setattr(mod, "_resolver", None)
    assert isinstance(get_secret_resolver(), EnvSecretResolver)


def test_factory_fernet_without_key_raises(monkeypatch):
    monkeypatch.delenv("DTE_SECRETS_KEY", raising=False)
    monkeypatch.setenv("DTE_SECRETS_BACKEND", "fernet")
    import dte.secrets as mod
    monkeypatch.setattr(mod, "_resolver", None)
    with pytest.raises(RuntimeError, match="DTE_SECRETS_KEY"):
        get_secret_resolver()
