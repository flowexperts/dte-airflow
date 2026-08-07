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

    # Rate limiting on auth endpoints.
    # Set auth_rate_limit_enabled=False in test environments so serial unit
    # tests don't accidentally trip the per-IP window.
    auth_rate_limit_enabled: bool = True
    auth_login_rate_limit: str = "5/minute"
    auth_register_rate_limit: str = "3/minute"

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

    # Multi-tenancy (plan 030). Off by default — ship migrations first, flip
    # the flag only after CI is green for two consecutive weeks.
    # When off: tenant_id is always "default", RLS session var is not set,
    # and fake stores don't filter by tenant.
    multi_tenant_enabled: bool = False

    # Root key for wrapping per-tenant Fernet keys (plan 030).
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    root_key: str | None = None

    # Distributed run execution via a Postgres-backed job queue (plan 046).
    # Off by default: `POST /trigger` keeps spawning an in-process
    # asyncio.create_task, exactly as before. When on, trigger enqueues a
    # procrastinate job instead and a separate `python -m dte.worker`
    # process executes it.
    job_queue_enabled: bool = False

    # Whether the deployment's output filesystem is shared across the API
    # and worker processes (e.g. an RWX NFS/EFS mount), rather than each
    # pod's own local disk. Only consulted when job_queue_enabled is True:
    # if the FS is *not* shared, `local_fs`-backed sources/destinations are
    # rejected at trigger time (422) because the worker pod can't see files
    # the API pod wrote, or vice versa. Default False — the safe assumption
    # for a k8s deployment with per-pod ephemeral storage.
    shared_output_fs: bool = False

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
