"""record_event: one row per step or phase, its terminal event updates it in place."""
from dte.airflow.operators import record_event


def test_steps_and_phases_keep_their_own_rows():
    events = []
    record_event(events, None, "load source s1", "started")
    record_event(events, None, "load source s1", "completed")
    record_event(events, 0, "filter", "started")
    record_event(events, None, "execute + write to json", "started")
    record_event(events, None, "execute + write to json", "failed", "IOError: boom")
    assert [(e["step_index"], e["op"], e["status"]) for e in events] == [
        (None, "load source s1", "completed"),
        (0, "filter", "started"),
        (None, "execute + write to json", "failed"),
    ]
    assert events[2]["message"] == "IOError: boom" and events[2]["finished_at"]
    assert events[1]["finished_at"] is None
