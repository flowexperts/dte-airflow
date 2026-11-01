"""Airflow plugin: the DTE API + UI inside the Airflow 3 api-server."""
from airflow.plugins_manager import AirflowPlugin

from dte.api.main import app

# The UI is a `react_apps` bundle (plan 066): Airflow loads it into its own
# page, so DTE shares Airflow's theme, fonts and router — no iframe. Every
# entry loads the same bundle; its url_route tells the bundle which section
# to open.
_BUNDLE = "/dte/ui/dte.umd.js"


class DtePlugin(AirflowPlugin):
    name = "dte"
    fastapi_apps = [{"app": app, "url_prefix": "/dte", "name": "DTE"}]
    react_apps = [
        # Airflow 3.3 groups same-category plugin items into the rail's Plugins
        # menu: Plugins ▸ DTE Pipelines ▸ Transform / Quality Check (plan 067).
        # `dte` owns every pipeline route; `dte-quality` only lands on the filter.
        *(
            {"name": name, "bundle_url": _BUNDLE, "destination": "nav",
             "category": "DTE Pipelines", "url_route": route,
             "icon": "/dte/ui/icon.svg", "icon_dark_mode": "/dte/ui/icon-dark.svg"}
            for name, route in [("Transform", "dte"), ("Quality Check", "dte-quality")]
        ),
        # Shared building blocks sit beside Airflow's Connections under Admin.
        *(
            {"name": name, "bundle_url": _BUNDLE, "destination": "nav",
             "category": "admin", "url_route": f"dte-{path}"}
            for name, path in [
                ("DTE Sources", "sources"),
                ("DTE Destinations", "destinations"),
                ("DTE Lookup tables", "lookup-tables"),
            ]
        ),
        # A tab on every dag run page: the run_results view for that run.
        # Airflow passes {dagId, runId} as props; non-DTE DAGs get a note.
        {"name": "DTE Run", "bundle_url": _BUNDLE, "destination": "dag_run",
         "url_route": "dte-run"},
    ]
