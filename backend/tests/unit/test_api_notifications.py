"""Plan 070: notifications belong to the pipeline, not its schedule, and use
any notifier an installed Airflow provider registers."""
from __future__ import annotations

import pytest
from airflow.exceptions import AirflowNotFoundException

import dte.airflow.notify as notify
from tests.unit.test_api_pipeline_schedule import TX, _run, client  # noqa: F401  (fixture)

FAKE = "tests.fixtures.fake_notifier.FakeNotifier"
GOOD = {"notifier": FAKE, "params": {"target_conn_id": "ops"}, "on": ["failure", "success"]}


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    monkeypatch.setattr(notify, "available_notifiers", lambda: [FAKE])

    def get(cid):
        if cid != "ops":
            raise AirflowNotFoundException(cid)
        return object()
    monkeypatch.setattr(notify, "get_connection", get)


def test_lists_installed_notifiers(client):
    r = client[0].get("/api/notifiers")
    assert r.status_code == 200
    assert [n["name"] for n in r.json()] == ["FakeNotifier"]
    assert r.json()[0]["params"][0] == {"name": "target_conn_id", "required": True, "default": None}


def test_set_and_get_without_a_schedule(client):
    c, stores = client
    assert c.get("/api/pipelines/tx_pipe/schedule").json() is None
    r = c.put("/api/pipelines/tx_pipe/notifications", json=[GOOD])
    assert r.status_code == 200, r.text
    assert c.get("/api/pipelines/tx_pipe/notifications").json() == [GOOD]
    # A revision, so the DAG (and its callbacks) change.
    assert _run(stores["pipeline_revision"].latest_for_pipeline("tx_pipe")).config["notifications"] == [GOOD]


@pytest.mark.parametrize("bad,why", [
    ({**GOOD, "notifier": "os.system"}, "not an installed Airflow notifier"),
    ({**GOOD, "params": {}}, "target_conn_id"),
    ({**GOOD, "params": {"target_conn_id": "typo"}}, "typo"),
    ({**GOOD, "on": ["sometimes"]}, None),  # pydantic rejects the event
])
def test_bad_notification_422(client, bad, why):
    r = client[0].put("/api/pipelines/tx_pipe/notifications", json=[GOOD, bad])
    assert r.status_code == 422, r.text
    if why:
        assert r.json()["detail"]["code"] == "invalid_notification"
        assert r.json()["detail"]["index"] == 1 and why in r.json()["detail"]["message"]


def test_pipeline_put_keeps_notifications_when_omitted(client):
    c, _ = client
    c.put("/api/pipelines/tx_pipe/notifications", json=[GOOD])
    assert c.put("/api/pipelines/tx_pipe", json={**TX, "name": "renamed"}).status_code == 200
    assert c.get("/api/pipelines/tx_pipe/notifications").json() == [GOOD]


def test_pipeline_put_validates_notifications_too(client):
    r = client[0].put("/api/pipelines/tx_pipe", json={**TX, "notifications": [{**GOOD, "notifier": "os.system"}]})
    assert r.status_code == 422


def test_removing_the_schedule_keeps_notifications(client):
    c, _ = client
    c.put("/api/pipelines/tx_pipe/schedule", json={"cron_expr": "0 2 * * *"})
    c.put("/api/pipelines/tx_pipe/notifications", json=[GOOD])
    c.delete("/api/pipelines/tx_pipe/schedule")
    assert c.get("/api/pipelines/tx_pipe/notifications").json() == [GOOD]
