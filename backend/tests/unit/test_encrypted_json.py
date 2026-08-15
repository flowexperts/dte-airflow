"""EncryptedJSON must degrade gracefully on a row whose ciphertext cannot
be decrypted/parsed by the *current* resolver — a wrong-key rotation, a
resolver-type change (env <-> fernet), or plain corruption. A single rotten
row must never raise out of SQLAlchemy row hydration (it would 500 the
whole `GET /api/connections` collection).
"""
import json

import pytest
from cryptography.fernet import Fernet

from dte.secrets.encrypted_json import EncryptedJSON, UnreadableCredentials
from dte.secrets.env import EnvSecretResolver
from dte.secrets.fernet import FernetSecretResolver


def _decorator() -> EncryptedJSON:
    return EncryptedJSON()


def test_decrypt_under_wrong_fernet_key_returns_sentinel(monkeypatch):
    """Row encrypted under key A, read back under key B."""
    key_a = Fernet.generate_key()
    key_b = Fernet.generate_key()
    resolver_a = FernetSecretResolver(key_a)
    ciphertext = resolver_a.encrypt({"password": "hunter2"})

    resolver_b = FernetSecretResolver(key_b)
    import dte.secrets.encrypted_json as mod
    monkeypatch.setattr(mod, "get_secret_resolver", lambda: resolver_b)

    result = _decorator().process_result_value(ciphertext, dialect=None)
    assert isinstance(result, UnreadableCredentials)
    assert result == {}  # never leaks ciphertext or partial content
    assert result.unreadable is True


def test_env_resolver_reading_fernet_blob_returns_sentinel(monkeypatch):
    """Fernet ciphertext handed to the Env resolver raises JSONDecodeError
    internally — must also degrade to the sentinel, not raise."""
    ciphertext = FernetSecretResolver(Fernet.generate_key()).encrypt({"k": "v"})

    import dte.secrets.encrypted_json as mod
    monkeypatch.setattr(mod, "get_secret_resolver", lambda: EnvSecretResolver())

    result = _decorator().process_result_value(ciphertext, dialect=None)
    assert isinstance(result, UnreadableCredentials)
    assert result == {}


def test_fernet_resolver_reading_env_plaintext_json_still_raises_cleanly(monkeypatch):
    """Sanity: an Env-resolver blob (bare JSON, not a Fernet token) handed to
    the Fernet resolver also degrades instead of raising InvalidToken."""
    ciphertext = EnvSecretResolver().encrypt({"k": "v"})

    import dte.secrets.encrypted_json as mod
    monkeypatch.setattr(mod, "get_secret_resolver", lambda: FernetSecretResolver(Fernet.generate_key()))

    result = _decorator().process_result_value(ciphertext, dialect=None)
    assert isinstance(result, UnreadableCredentials)


def test_process_result_value_none_is_untouched():
    assert _decorator().process_result_value(None, dialect=None) == {}


def test_process_result_value_good_blob_decrypts_normally(monkeypatch):
    resolver = EnvSecretResolver()
    import dte.secrets.encrypted_json as mod
    monkeypatch.setattr(mod, "get_secret_resolver", lambda: resolver)
    ciphertext = resolver.encrypt({"user": "alice"})
    result = _decorator().process_result_value(ciphertext, dialect=None)
    assert result == {"user": "alice"}
    assert not isinstance(result, UnreadableCredentials)


def test_bind_param_preserves_original_ciphertext_for_sentinel(monkeypatch):
    """Re-saving a connection whose creds failed to decrypt must NOT
    overwrite the original ciphertext with an encryption of the sentinel —
    the exact original bytes must round-trip back out unchanged."""
    key_a = Fernet.generate_key()
    original_ciphertext = FernetSecretResolver(key_a).encrypt({"password": "hunter2"})

    import dte.secrets.encrypted_json as mod
    monkeypatch.setattr(mod, "get_secret_resolver", lambda: FernetSecretResolver(Fernet.generate_key()))

    dec = _decorator()
    sentinel = dec.process_result_value(original_ciphertext, dialect=None)
    assert isinstance(sentinel, UnreadableCredentials)

    rewritten = dec.process_bind_param(sentinel, dialect=None)
    assert rewritten == original_ciphertext


def test_bind_param_plain_dict_still_encrypts_normally(monkeypatch):
    resolver = EnvSecretResolver()
    import dte.secrets.encrypted_json as mod
    monkeypatch.setattr(mod, "get_secret_resolver", lambda: resolver)
    dec = _decorator()
    out = dec.process_bind_param({"user": "bob"}, dialect=None)
    assert json.loads(out.decode()) == {"user": "bob"}


def test_bind_param_none_passthrough():
    assert _decorator().process_bind_param(None, dialect=None) is None
