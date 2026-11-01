"""Centralised settings.

One `Settings` class, fed by environment variables, validated at import time.
Replaces scattered `os.getenv` calls with a typed, documented surface.

Direct `os.getenv` reads are kept in a few places on purpose:
- `dte/api/deps.py::_session_factory` — needs a lazy read so tests that never
  touch Postgres don't pay a startup cost. It falls back to `settings.database_url`.
"""
from __future__ import annotations

from typing import Literal

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

    # Hard stop on sweep size. Read via getattr by the sweep route since
    # plan 051, but never declared here — so `extra="ignore"` swallowed
    # DTE_EVAL_MAX_SWEEP_CELLS and the cap the error message told users to
    # raise was in fact a constant.
    eval_max_sweep_cells: int = 50

    # Pipelines as files (plan 090). `file` makes `DTE_PIPELINES_DIR` the
    # source of truth (one `<id>.yaml` each) for the API and the DAG factory;
    # `postgres` is today's behaviour. The dir must be shared by the
    # api-server and the dag-processor.
    pipeline_store: Literal["postgres", "file"] = "postgres"
    pipelines_dir: str = "pipelines"
    # Opt-in: commit each save/delete when the dir is a git checkout.
    pipelines_git_commit: bool = False

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
