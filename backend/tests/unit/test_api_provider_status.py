"""Which providers can actually run, before you spend a run finding out.

Reported after a comparison came back with two empty columns:

    claude: "Could not resolve authentication method. Expected one of
     api_key, auth_token, or credentials to be set..."

The key was simply unset. Nothing in the product said so — the wizard
offered Claude and OpenAI exactly as it offers regex, took an estimate,
launched a sweep, and only then surfaced an SDK message as a per-row error.

This is the same shape as the regex-needs-patterns gate: a provider that
cannot succeed should not be offered, and the reason should name the fix.
Refuse at the edge, filter in the UI so the refusal never has to happen.

The endpoint reports *configuration*, not validity. A key that is present
but expired still has to fail at call time — proving otherwise would need a
billable request per page load, and would be wrong the moment it is revoked.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dte.api.main import app


@pytest.fixture
def client(fake_stores):
    return TestClient(app)


class TestReadiness:
    def test_regex_is_always_ready(self, client, monkeypatch):
        # Deterministic, offline, no credentials. It is the reason a
        # comparison can run for nothing, so it must never gate.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        body = client.get("/api/providers/structure").json()
        assert body["providers"]["regex"]["configured"] is True

    def test_claude_needs_a_key(self, client, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        body = client.get("/api/providers/structure").json()
        assert body["providers"]["claude"]["configured"] is False
        assert "ANTHROPIC_API_KEY" in body["providers"]["claude"]["reason"]

    def test_openai_needs_a_key(self, client, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        body = client.get("/api/providers/structure").json()
        assert body["providers"]["openai"]["configured"] is False
        assert "OPENAI_API_KEY" in body["providers"]["openai"]["reason"]

    def test_a_present_key_reads_as_configured(self, client, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-whatever")
        body = client.get("/api/providers/structure").json()
        assert body["providers"]["claude"]["configured"] is True
        assert body["providers"]["claude"]["reason"] is None

    def test_an_empty_key_is_not_configured(self, client, monkeypatch):
        # Compose writes `ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}`, so the
        # variable exists and is empty when nothing supplied it. Presence is
        # not the test; a non-blank value is.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
        body = client.get("/api/providers/structure").json()
        assert body["providers"]["claude"]["configured"] is False

    def test_the_key_itself_is_never_returned(self, client, monkeypatch):
        # A readiness probe that echoes the secret turns a convenience into
        # a disclosure on every page load.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-supersecret")
        assert "supersecret" not in client.get("/api/providers/structure").text

    def test_every_structure_provider_is_reported(self, client):
        # A provider missing from this map would silently render as
        # unavailable in the wizard and could never be selected.
        from dte.models.pipeline import StructureStep

        declared = set(StructureStep.model_fields["provider"].annotation.__args__)
        assert set(client.get("/api/providers/structure").json()["providers"]) == declared
