"""Plan 070: retries/timeout ride the schedule; notifications ride the pipeline."""
from datetime import timedelta
from types import SimpleNamespace as NS

from dte.airflow.dag_factory import _dag_for

FAKE = "tests.fixtures.fake_notifier.FakeNotifier"


def _rev(schedule=None, notifications=None):
    return NS(id="r1", pipeline_id="p1",
              config={"name": "P", "schedule": schedule, "notifications": notifications or []})


def test_defaults_no_retries_default_timeout_no_callbacks():
    task = _dag_for(_rev()).get_task("run")
    assert task.retries == 0
    assert task.execution_timeout == timedelta(minutes=30)
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


def test_timeout_falls_back_to_run_timeout_seconds(monkeypatch):
    """Plan 086: `run_timeout_seconds` was declared and never read, so an
    unscheduled run had no timeout at all."""
    monkeypatch.setenv("DTE_RUN_TIMEOUT_SECONDS", "120")
    assert _dag_for(_rev()).get_task("run").execution_timeout == timedelta(seconds=120)


def test_one_active_run_by_default_even_unscheduled():
    """Plan 089: manual runs must not write the same destination concurrently."""
    assert _dag_for(_rev()).max_active_runs == 1
    assert _dag_for(_rev({"cron_expr": "0 1 * * *"})).max_active_runs == 1


def test_overlap_allow_lifts_the_limit():
    assert _dag_for(_rev({"cron_expr": "0 1 * * *", "overlap": "allow"})).max_active_runs == 16


def test_assets_mode_triggers_on_upstream_assets():
    from airflow.sdk.definitions.timetables.assets import AssetTriggeredTimetable

    dag = _dag_for(_rev({"mode": "assets", "assets": ["dte://pg/mart/orders"]}))
    assert isinstance(dag.timetable, AssetTriggeredTimetable)
    assert [a.uri for a in dag.timetable.asset_condition.objects] == ["dte://pg/mart/orders"]


def test_doc_md_is_the_pipeline_yaml_with_a_link_back():
    import yaml
    rev = _rev()
    doc = _dag_for(rev).doc_md
    assert "plugin/dte/pipelines/detail?id=p1" in doc
    body = doc.split("```yaml\n", 1)[1].rsplit("```", 1)[0]
    assert yaml.safe_load(body) == rev.config
