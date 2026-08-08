"""ScheduleBase model validation (plan 047 task 2)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from dte.models.pipeline import ScheduleBase


def _schedule(**overrides) -> dict:
    base = {
        "id": "sch_1",
        "pipeline_id": "p1",
        "cron_expr": "0 2 * * *",
    }
    base.update(overrides)
    return base


def test_schedule_defaults():
    s = ScheduleBase(**_schedule())
    assert s.timezone == "UTC"
    assert s.params == {}
    assert s.enabled is True
    assert s.overlap == "skip"
    assert s.tenant_id == "default"


def test_schedule_overlap_allow():
    s = ScheduleBase(**_schedule(overlap="allow"))
    assert s.overlap == "allow"


def test_schedule_overlap_rejects_unknown_value():
    with pytest.raises(ValidationError):
        ScheduleBase(**_schedule(overlap="retry"))


def test_schedule_requires_pipeline_id_and_cron_expr():
    with pytest.raises(ValidationError):
        ScheduleBase(id="sch_2")


def test_schedule_params_round_trip():
    s = ScheduleBase(**_schedule(params={"region": "us"}))
    assert s.params == {"region": "us"}
