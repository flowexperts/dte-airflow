"""Shared slowapi Limiter — its own module so route files and main.py can
both import it without circular deps."""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
