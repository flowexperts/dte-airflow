"""Tests for the plan-046 job-queue feature flags."""
from __future__ import annotations

from dte.config import get_settings


def test_job_queue_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DTE_JOB_QUEUE_ENABLED", raising=False)
    assert get_settings().job_queue_enabled is False


def test_job_queue_enabled_via_env(monkeypatch):
    monkeypatch.setenv("DTE_JOB_QUEUE_ENABLED", "true")
    assert get_settings().job_queue_enabled is True


def test_shared_output_fs_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DTE_SHARED_OUTPUT_FS", raising=False)
    assert get_settings().shared_output_fs is False


def test_shared_output_fs_enabled_via_env(monkeypatch):
    monkeypatch.setenv("DTE_SHARED_OUTPUT_FS", "true")
    assert get_settings().shared_output_fs is True
