"""Plan 090: with DTE_PIPELINE_STORE=file the DAG factory reads
DTE_PIPELINES_DIR — no DB at parse time, one bad file drops one DAG."""
import pytest

from dte.airflow import dag_factory
from dte.airflow.trigger import revision_tag
from dte.store.files import read_revision


@pytest.fixture
def pipelines(tmp_path, monkeypatch):
    monkeypatch.setenv("DTE_PIPELINE_STORE", "file")
    monkeypatch.setenv("DTE_PIPELINES_DIR", str(tmp_path))

    def no_db():
        raise AssertionError("the DAG factory touched the DB")

    monkeypatch.setattr("dte.airflow.db.sync_engine", no_db)
    return tmp_path


def _file(d, pid, extra=""):
    (d / f"{pid}.yaml").write_text(f"id: {pid}\nname: {pid.upper()}\n{extra}")


def test_dag_per_file_tagged_with_the_file_revision(pipelines):
    _file(pipelines, "a", "schedule:\n  cron_expr: 0 1 * * *\n")
    dags = dag_factory.build_dags()
    assert list(dags) == ["dte__a"]
    dag = dags["dte__a"]
    rev = read_revision(pipelines / "a.yaml")
    assert revision_tag(rev.id) in dag.tags
    assert dag.get_task("run").revision_id == rev.id
    assert dag.timetable.summary == "0 1 * * *"


def test_a_broken_file_drops_only_its_own_dag(pipelines, caplog):
    _file(pipelines, "good")
    (pipelines / "syntax.yaml").write_text("id: syntax\nname: [unclosed\n")
    _file(pipelines, "badstep", "steps:\n- op: nope\n")
    _file(pipelines, "renamed")
    (pipelines / "renamed.yaml").rename(pipelines / "other.yaml")  # id != file name
    assert list(dag_factory.build_dags()) == ["dte__good"]
    # A bad cron builds and is caught per DAG by Airflow's own dag.validate().
    for name in ("syntax", "badstep", "other"):
        assert f"{name}.yaml" in caplog.text


def test_non_yaml_and_subdirs_are_ignored(pipelines):
    _file(pipelines, "a")
    (pipelines / "README.md").write_text("# pipelines")
    (pipelines / "sources").mkdir()
    (pipelines / "sources" / "s.yaml").write_text("id: s\n")
    assert list(dag_factory.build_dags()) == ["dte__a"]


def test_parses_a_thousand_files_with_no_db(pipelines):
    for i in range(1000):
        _file(pipelines, f"p{i:04d}")
    assert len(dag_factory.build_dags()) == 1000


def test_postgres_mode_still_reads_the_db(monkeypatch):
    monkeypatch.delenv("DTE_PIPELINE_STORE", raising=False)

    class Read(Exception):
        pass

    def db():
        raise Read

    monkeypatch.setattr("dte.airflow.db.sync_engine", db)
    with pytest.raises(Read):
        dag_factory.build_dags()
