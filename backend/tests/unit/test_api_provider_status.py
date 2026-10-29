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

Keys are Airflow connections (plan 072): `anthropic_default` /
`openai_default` unless a step names its own.

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


def _conns(by_provider):
    return lambda provider: by_provider.get(provider, [])


class TestReadiness:
    def test_regex_is_always_ready(self, client, monkeypatch):
        # Deterministic, offline, no credentials. It is the reason a
        # comparison can run for nothing, so it must never gate.
        monkeypatch.setattr("dte.airflow.connections.model_connections", _conns({}))
        body = client.get("/api/providers/structure").json()
        assert body["providers"]["regex"]["configured"] is True

    def test_claude_needs_its_default_connection(self, client, monkeypatch):
        monkeypatch.setattr("dte.airflow.connections.model_connections", _conns({}))
        body = client.get("/api/providers/structure").json()
        assert body["providers"]["claude"]["configured"] is False
        assert "anthropic_default" in body["providers"]["claude"]["reason"]

    def test_openai_needs_its_default_connection(self, client, monkeypatch):
        monkeypatch.setattr("dte.airflow.connections.model_connections", _conns({}))
        body = client.get("/api/providers/structure").json()
        assert body["providers"]["openai"]["configured"] is False
        assert "openai_default" in body["providers"]["openai"]["reason"]

    def test_a_default_connection_reads_as_configured(self, client, monkeypatch):
        monkeypatch.setattr(
            "dte.airflow.connections.model_connections",
            _conns({"claude": ["anthropic_default"]}),
        )
        body = client.get("/api/providers/structure").json()
        assert body["providers"]["claude"]["configured"] is True
        assert body["providers"]["claude"]["reason"] is None

    def test_connections_are_listed_for_the_picker(self, client, monkeypatch):
        # A non-default connection alone does not make the provider ready —
        # a step with no connection_id still reads the default — but it is
        # offered so a step can pick it.
        monkeypatch.setattr(
            "dte.airflow.connections.model_connections",
            _conns({"claude": ["anthropic_billing"]}),
        )
        claude = client.get("/api/providers/structure").json()["providers"]["claude"]
        assert claude["connections"] == ["anthropic_billing"]
        assert claude["configured"] is False

    def test_no_secret_is_ever_returned(self, client, monkeypatch):
        # Only conn ids cross the wire; the route never sees a key at all.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-supersecret")
        monkeypatch.setattr("dte.airflow.connections.model_connections", _conns({}))
        assert "supersecret" not in client.get("/api/providers/structure").text

    def test_every_structure_provider_is_reported(self, client, monkeypatch):
        # A provider missing from this map would silently render as
        # unavailable in the wizard and could never be selected.
        from dte.models.pipeline import StructureStep

        monkeypatch.setattr("dte.airflow.connections.model_connections", _conns({}))
        declared = set(StructureStep.model_fields["provider"].annotation.__args__)
        assert set(client.get("/api/providers/structure").json()["providers"]) == declared
