import pytest
import dte.api.deps as deps


def test_missing_database_url_raises_when_store_accessed(monkeypatch):
    """deps.py must NOT silently fall back to any in-memory store.
    Without DATABASE_URL the getter must raise so callers see the
    misconfiguration immediately."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    deps._session_factory.cache_clear()
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        deps.get_pipeline_store()
