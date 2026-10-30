"""Plan 070: retries/timeout ride the schedule; notifications ride the pipeline."""
from datetime import timedelta
from types import SimpleNamespace as NS

from dte.airflow.dag_factory import _dag_for

FAKE = "tests.fixtures.fake_notifier.FakeNotifier"


def _rev(schedule=None, notifications=None):
    return NS(id="r1", pipeline_id="p1",
              config={"name": "P", "schedule": schedule, "notifications": notifications or []})


def test_defaults_no_retries_no_timeout_no_callbacks():
    task = _dag_for(_rev()).get_task("run")
    assert task.retries == 0
    assert task.execution_timeout is None
    assert not task.on_failure_callback and not task.on_success_callback


def test_schedule_sets_retries_and_timeout():
    sc = {"cron_expr": "0 1 * * *", "retries": 2, "retry_delay_s": 60, "timeout_s": 600}
    task = _dag_for(_rev(sc)).get_task("run")
    assert task.retries == 2
    assert task.retry_delay == timedelta(seconds=60)
    assert task.execution_timeout == timedelta(seconds=600)


def test_notifications_need_no_schedule():
    """Manual-only pipelines notify too."""
    n = [{"notifier": FAKE, "params": {"target_conn_id": "ops"}, "on": ["failure", "success"]}]
    task = _dag_for(_rev(None, n)).get_task("run")
    assert task.on_failure_callback and task.on_success_callback
    assert not task.on_retry_callback
