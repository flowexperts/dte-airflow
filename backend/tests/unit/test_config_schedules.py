"""Tests for the plan-047 schedule feature flags."""
from __future__ import annotations

from dte.config import get_settings


def test_schedules_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DTE_SCHEDULES_ENABLED", raising=False)
    assert get_settings().schedules_enabled is False


def test_schedules_enabled_via_env(monkeypatch):
    monkeypatch.setenv("DTE_SCHEDULES_ENABLED", "true")
    assert get_settings().schedules_enabled is True


def test_schedule_grace_seconds_default(monkeypatch):
    monkeypatch.delenv("DTE_SCHEDULE_GRACE_SECONDS", raising=False)
    assert get_settings().schedule_grace_seconds == 900


def test_schedule_grace_seconds_via_env(monkeypatch):
    monkeypatch.setenv("DTE_SCHEDULE_GRACE_SECONDS", "60")
    assert get_settings().schedule_grace_seconds == 60
