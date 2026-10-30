"""Pipeline notifications through Airflow's own notifiers (plan 070).

A notification is `{notifier, params, on}`: `notifier` is the class path of
any notifier an installed provider registers (Slack, SMTP, Teams, SNS,
PagerDuty, ...), `params` its constructor kwargs, `on` the run events that
fire it. Templated params can use `{{ dte_message }}` and `{{ dte_event }}`.

Only registered notifiers are ever imported, so a saved class path can't
reach arbitrary code. Sending never raises: a broken notification must not
mask the run's own outcome.
"""
from __future__ import annotations

import importlib
import inspect
import logging
from functools import partial

log = logging.getLogger(__name__)

_CALLBACK = {"failure": "on_failure_callback", "success": "on_success_callback", "retry": "on_retry_callback"}


def available_notifiers() -> list[str]:
    from airflow.providers_manager import ProvidersManager

    return sorted(ProvidersManager().notification)


def get_connection(conn_id: str):
    from airflow.hooks.base import BaseHook

    return BaseHook.get_connection(conn_id)


def _load(path: str):
    if path not in available_notifiers():
        raise ValueError(f"{path!r} is not an installed Airflow notifier")
    module, _, name = path.rpartition(".")
    return getattr(importlib.import_module(module), name)


def describe(path: str) -> dict:
    """The notifier's constructor params, for the UI to prefill."""
    cls = _load(path)
    params = [
        {"name": p.name, "required": p.default is inspect.Parameter.empty,
         "default": None if p.default is inspect.Parameter.empty else repr(p.default)}
        for p in list(inspect.signature(cls.__init__).parameters.values())[1:]
        if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    ]
    return {"notifier": path, "name": cls.__name__, "params": params,
            "doc": (inspect.getdoc(cls) or "").split("\n\n")[0]}


def problem(n: dict) -> str | None:
    """Why notification `n` can't send, or None. Checked at save time."""
    from airflow.exceptions import AirflowNotFoundException

    try:
        cls = _load(n["notifier"])
    except (ValueError, ImportError) as e:
        return str(e)
    params = n.get("params") or {}
    try:
        cls(**params)  # notifiers only store their args; this catches missing/unknown ones
    except TypeError as e:
        return f"{cls.__name__}: {e}"
    for k, v in params.items():
        if k.endswith("_conn_id") and isinstance(v, str) and "{{" not in v:
            try:
                get_connection(v)
            except AirflowNotFoundException:
                return f"no Airflow connection {v!r} (param {k}); create it under Admin > Connections"
    return None


def _message(event: str, context) -> str:
    dag = context["dag"]
    name = getattr(dag, "dag_display_name", None) or dag.dag_id
    msg = f"DTE pipeline {name}: {event}\nDAG: {dag.dag_id}\nRun: {context['run_id']}"
    if event != "success" and context.get("exception"):
        msg += f"\nError: {context['exception']}"
    return msg


def send(n: dict, event: str, context) -> None:
    try:
        notifier = _load(n["notifier"])(**(n.get("params") or {}))
        # Passed as variables, so text in the error is never itself rendered.
        notifier({**context, "dte_message": _message(event, context), "dte_event": event})
    except Exception as e:
        log.warning("notification %s on %s failed: %s", n.get("notifier"), event, e)


def callbacks(notifications: list[dict]) -> dict:
    """Operator kwargs: `on_<event>_callback` lists for the given notifications."""
    out: dict[str, list] = {}
    for n in notifications or []:
        for event in n.get("on") or ["failure"]:
            out.setdefault(_CALLBACK[event], []).append(partial(send, n, event))
    return out
