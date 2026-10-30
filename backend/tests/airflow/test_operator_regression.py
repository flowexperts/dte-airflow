"""The regression check reads history from `run_results` only (plan 075): a
task's DB credentials may not reach Airflow's `dag_run` table."""
import importlib
import sys
from types import ModuleType, SimpleNamespace


def _operators(monkeypatch):
    """Import `dte.airflow.operators` with the two Airflow names it needs
    stubbed, so this runs without Airflow installed."""
    if "airflow" not in sys.modules:
        exc, sdk = ModuleType("airflow.exceptions"), ModuleType("airflow.sdk")
        exc.AirflowFailException = type("AirflowFailException", (Exception,), {})
        sdk.BaseOperator = type("BaseOperator", (), {"__init__": lambda self, **kw: None})
        for name, mod in {"airflow": ModuleType("airflow"), "airflow.exceptions": exc, "airflow.sdk": sdk}.items():
            monkeypatch.setitem(sys.modules, name, mod)
        monkeypatch.delitem(sys.modules, "dte.airflow.operators", raising=False)
    return importlib.import_module("dte.airflow.operators")


def test_regression_compares_against_run_results_history(monkeypatch):
    operators = _operators(monkeypatch)
    seen = {}

    def fake_history(engine, eval_set_id, limit=50):
        seen["args"] = (engine, eval_set_id, limit)
        return [{"id": "prior", "config_digest": "d", "labels_version": 1,
                 "scores": {"macro_f1": 0.9, "macro_f1_interval": [0.88, 0.92]}}]

    monkeypatch.setattr(operators, "eval_history", fake_history)
    res = SimpleNamespace(config_digest="d", labels_version=1,
                          scores={"macro_f1": 0.5, "macro_f1_interval": [0.45, 0.55]})

    got = operators.DtePipelineOperator._regression("engine", "es1", res, "now")

    assert seen["args"] == ("engine", "es1", 50)
    assert got["previous_run_id"] == "prior"
