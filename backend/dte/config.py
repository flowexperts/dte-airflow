"""Centralised settings.

One `Settings` class, fed by environment variables, validated at import time.
Replaces scattered `os.getenv` calls with a typed, documented surface.

Direct `os.getenv` reads are kept in a few places on purpose:
- `dte/api/deps.py::_session_factory` — needs a lazy read so tests that never
  touch Postgres don't pay a startup cost. It falls back to `settings.database_url`.
- `dte/secrets/__init__.py` — the resolver picker is invoked before Settings
  might exist. It still reads env directly and that's fine.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # No env_file — 12-factor. Docker Compose / `uv run --env-file` supply env.
    # Loading .env implicitly here would break tests that assume a clean env
    # and would leak dev secrets into pytest runs.
    model_config = SettingsConfigDict(
        env_prefix="DTE_",
        extra="ignore",
    )

    # Auth
    jwt_secret: str | None = None
    jwt_ttl_seconds: int = 60 * 60 * 24
    allow_registration: bool = True

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # Admin
    admin_enabled: bool = False
    admin_secret_key: str | None = None

    # Secrets
    secrets_backend: Literal["env", "fernet", "auto"] = "auto"
    secrets_key: str | None = None

    # Database (NOT under DTE_ prefix — standard 12-factor name)
    database_url: str | None = Field(default=None, alias="DATABASE_URL")

    # Run guardrails
    run_timeout_seconds: int = 60 * 30  # 30 min default
    run_max_rows: int = 10_000_000

    # Logging
    log_level: str = "INFO"
    log_json: bool = False  # default False in dev; set true in prod

    @field_validator("cors_origins")
    @classmethod
    def _strip_cors(cls, v: str) -> str:
        return ",".join(o.strip() for o in v.split(",") if o.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        return [o for o in self.cors_origins.split(",") if o]


def get_settings() -> Settings:
    """Read settings fresh from the environment on each call.

    Not cached: pytest fixtures monkeypatch env between tests and we want the
    next `get_settings()` call to see the new values. The parse is O(microseconds)
    and only happens on request-path boundaries (auth check, run trigger).
    """
    return Settings()


# Back-compat shim for code that used the previous cached form.
def _noop_cache_clear() -> None:  # pragma: no cover
    return None


get_settings.cache_clear = _noop_cache_clear  # type: ignore[attr-defined]
