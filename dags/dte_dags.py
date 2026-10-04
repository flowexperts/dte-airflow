from dte.airflow.dag_factory import build_dags

globals().update(build_dags())
