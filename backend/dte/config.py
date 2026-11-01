"""Centralised settings.

One `Settings` class, fed by environment variables, validated at import time.
Replaces scattered `os.getenv` calls with a typed, documented surface.

Direct `os.getenv` reads are kept in a few places on purpose:
- `dte/api/deps.py::_session_factory` — needs a lazy read so tests that never
  touch Postgres don't pay a startup cost. It falls back to `settings.database_url`.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # No env_file — 12-factor. Docker Compose / `uv run --env-file` supply env.
    # Loading .env implicitly here would break tests that assume a clean env
    # and would leak dev secrets into pytest runs.
    model_config = SettingsConfigDict(
        env_prefix="DTE_",
        extra="ignore",
    )

    # Database (NOT under DTE_ prefix — standard 12-factor name)
    database_url: str | None = Field(default=None, alias="DTE_DATABASE_URL")

    # Run guardrails
    run_timeout_seconds: int = 60 * 30  # 30 min default
    run_max_rows: int = 10_000_000

    # DuckDB resource limits, applied to every connection (plan 086). Unset
    # means DuckDB's own default: 80% of RAM and every core, per connection.
    duckdb_memory_limit: str | None = None  # e.g. "4GB"
    duckdb_threads: int | None = None
    duckdb_temp_dir: str | None = None  # where DuckDB spills past memory_limit

    # Hard stop on sweep size. Read via getattr by the sweep route since
    # plan 051, but never declared here — so `extra="ignore"` swallowed
    # DTE_EVAL_MAX_SWEEP_CELLS and the cap the error message told users to
    # raise was in fact a constant.
    eval_max_sweep_cells: int = 50

    # Logging
    log_level: str = "INFO"
    log_json: bool = False  # default False in dev; set true in prod


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
