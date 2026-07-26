"""Shared slowapi Limiter — its own module so route files and main.py can
both import it without circular deps.

Production: ``DTE_AUTH_RATE_LIMIT_ENABLED=true`` (the default).
Tests: the ``conftest.py`` autouse fixture disables the limiter so serial unit
tests that call login/register multiple times don't trip the per-IP window.
``test_rate_limit.py`` re-enables it just for its own tests.

Limits are configurable via settings:
  DTE_AUTH_LOGIN_RATE_LIMIT    (default: "5/minute")
  DTE_AUTH_REGISTER_RATE_LIMIT (default: "3/minute")
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from dte.config import get_settings

_settings = get_settings()

limiter = Limiter(
    key_func=get_remote_address,
    enabled=_settings.auth_rate_limit_enabled,
)
