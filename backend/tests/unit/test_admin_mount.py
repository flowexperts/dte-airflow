"""Feature-flag behavior of the FastAdmin mount.

The mount itself is imported lazily and requires a live Postgres for
model registration, so we can't exhaustively test it in-process. We
just verify the feature flag gate: off by default, and mount_admin
returns False when the flag is unset."""
from __future__ import annotations

import importlib


def test_admin_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DTE_ADMIN_ENABLED", raising=False)
    from dte.admin import mount_admin

    class _StubApp:
        def mount(self, *a, **k):  # pragma: no cover — should not be called
            raise AssertionError("mount() should not be called when flag is off")

    assert mount_admin(_StubApp()) is False


def test_admin_flag_off_when_set_to_falsy_string(monkeypatch):
    monkeypatch.setenv("DTE_ADMIN_ENABLED", "false")
    from dte.admin import mount_admin

    class _StubApp:
        def mount(self, *a, **k):
            raise AssertionError("mount() should not be called")

    assert mount_admin(_StubApp()) is False


def test_admin_module_imports_cleanly():
    """`from dte.admin import mount_admin` must not raise even without
    fastadmin or a live DB."""
    mod = importlib.import_module("dte.admin")
    assert hasattr(mod, "mount_admin")
