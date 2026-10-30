"""Plan 070: a scheduled run's dates come from its logical date."""
import pendulum

from dte.airflow.operators import run_as_of


def test_logical_date_in_schedule_timezone():
    ld = pendulum.datetime(2026, 3, 1, 20, 0, tz="UTC")  # 01:30 on 2 Mar in Kolkata
    assert run_as_of({"logical_date": ld}, {"schedule": {"timezone": "Asia/Kolkata"}}).date().isoformat() == "2026-03-02"


def test_manual_run_has_no_as_of():
    assert run_as_of({"logical_date": None}, {"schedule": None}) is None
