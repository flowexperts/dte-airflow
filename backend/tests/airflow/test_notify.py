"""Plan 070: pipeline notifications are any notifier an Airflow provider registers."""
import pytest
from airflow.exceptions import AirflowNotFoundException
from airflow.sdk import DAG

import dte.airflow.notify as notify
from tests.fixtures import fake_notifier

FAKE = "tests.fixtures.fake_notifier.FakeNotifier"


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    fake_notifier.SENT.clear()
    monkeypatch.setattr(notify, "available_notifiers", lambda: [FAKE])

    def get(cid):
        if cid != "ops":
            raise AirflowNotFoundException(cid)
        return object()
    monkeypatch.setattr(notify, "get_connection", get)


def _ctx():
    return {"dag": DAG("dte__p1", dag_display_name="Orders", schedule=None), "run_id": "run-1",
            "exception": RuntimeError("bucket {{ gone }}")}


def test_describe_lists_constructor_params():
    d = notify.describe(FAKE)
    assert d["name"] == "FakeNotifier"
    assert {p["name"]: p["required"] for p in d["params"]} == {"target_conn_id": True, "text": False}


@pytest.mark.parametrize("n,problem", [
    ({"notifier": FAKE, "params": {"target_conn_id": "ops"}}, None),
    ({"notifier": "os.system", "params": {}}, "not an installed Airflow notifier"),
    ({"notifier": FAKE, "params": {}}, "target_conn_id"),                        # missing required arg
    ({"notifier": FAKE, "params": {"target_conn_id": "ops", "nope": 1}}, "nope"),  # unknown arg
    ({"notifier": FAKE, "params": {"target_conn_id": "typo"}}, "no Airflow connection 'typo'"),
])
def test_problem(n, problem):
    got = notify.problem(n)
    assert got is None if problem is None else problem in got


def test_send_renders_message_into_template_fields():
    notify.send({"notifier": FAKE, "params": {"target_conn_id": "ops"}}, "failure", _ctx())
    [sent] = fake_notifier.SENT
    assert sent["conn"] == "ops"
    assert "Orders" in sent["text"] and "failure" in sent["text"]
    assert "bucket {{ gone }}" in sent["text"]  # error text is data, not a template


def test_send_refuses_unregistered_notifier_and_never_raises(caplog):
    notify.send({"notifier": "os.system", "params": {}}, "failure", _ctx())
    assert "not an installed Airflow notifier" in caplog.text


def test_callbacks_group_by_event():
    cbs = notify.callbacks([{"notifier": FAKE, "params": {}, "on": ["failure", "retry"]},
                            {"notifier": FAKE, "params": {}, "on": ["success"]}])
    assert {k: len(v) for k, v in cbs.items()} == {
        "on_failure_callback": 1, "on_retry_callback": 1, "on_success_callback": 1}
    assert notify.callbacks([]) == {}
