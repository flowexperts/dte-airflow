"""Plan 090: pipelines as files — the YAML format, the file store, and a
file as a revision."""
import shutil
import subprocess

import pytest
import yaml

from dte.models.pipeline import Pipeline, PipelineBase
from dte.store.files import (
    FilePipelineStore,
    export_pipelines,
    file_revision,
    load_pipeline,
    read_revision,
)


def _pipeline(id="p1", name="P one", **kw):
    base = PipelineBase(id=id, name=name, sources=["orders"],
                        steps=[{"op": "filter", "expr": "amount > 100"}], output_id="out", **kw)
    return Pipeline(**base.model_dump())


async def test_save_writes_the_models_own_yaml(tmp_path):
    p = _pipeline()
    await FilePipelineStore(tmp_path).save(p)
    path = tmp_path / "p1.yaml"
    assert path.exists()
    assert yaml.safe_load(path.read_text()) == p.model_dump(mode="json", exclude={"created_at", "updated_at"})


async def test_get_list_delete(tmp_path):
    store = FilePipelineStore(tmp_path)
    await store.save(_pipeline("a", "A"))
    await store.save(_pipeline("b", "B"))
    got = await store.get("a")
    assert got.name == "A" and got.steps == [{"op": "filter", "expr": "amount > 100"}]
    assert got.updated_at is not None
    assert {p.id for p in await store.list()} == {"a", "b"}
    assert await store.get("missing") is None
    assert await store.delete("a") is True
    assert await store.delete("a") is False
    assert [p.id for p in await store.list()] == ["b"]


async def test_one_unreadable_file_does_not_drop_the_list(tmp_path):
    store = FilePipelineStore(tmp_path)
    await store.save(_pipeline("a", "A"))
    (tmp_path / "junk.yaml").write_text("{ not yaml")
    assert [p.id for p in await store.list()] == ["a"]


async def test_name_is_unique_like_the_db_constraint(tmp_path):
    store = FilePipelineStore(tmp_path)
    await store.save(_pipeline("a", "Same"))
    with pytest.raises(ValueError, match="already exists"):
        await store.save(_pipeline("b", "Same"))
    await store.save(_pipeline("a", "Same"))  # re-saving yourself is fine


async def test_id_cannot_escape_the_directory(tmp_path):
    store = FilePipelineStore(tmp_path / "pipelines")
    with pytest.raises(ValueError):
        await store.save(_pipeline("../evil", "E"))
    assert await store.get("../evil") is None
    assert not (tmp_path / "evil.yaml").exists()


async def test_index_store_is_written_alongside_the_file(tmp_path):
    class Index:
        rows: dict = {}

        async def save(self, p):
            self.rows[p.id] = p

        async def delete(self, id):
            return self.rows.pop(id, None) is not None

    index = Index()
    store = FilePipelineStore(tmp_path, index=index)
    await store.save(_pipeline("a", "A"))
    assert "a" in index.rows
    await store.delete("a")
    assert "a" not in index.rows


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def _git_repo(path):
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    return path


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
async def test_save_commits_when_opted_in_and_dir_is_a_checkout(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    store = FilePipelineStore(repo, git_commit=True)
    await store.save(_pipeline())
    assert "p1.yaml" in _git(repo, "log", "--name-only", "--format=%s")
    await store.save(_pipeline())  # unchanged content: no empty commit
    assert len(_git(repo, "log", "--format=%H").split()) == 1
    await store.delete("p1")
    assert len(_git(repo, "log", "--format=%H").split()) == 2
    assert _git(repo, "status", "--porcelain") == ""


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
async def test_no_commit_unless_opted_in(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    await FilePipelineStore(repo).save(_pipeline())
    assert subprocess.run(["git", "-C", str(repo), "log"], capture_output=True).returncode != 0  # no commits


async def test_opt_in_outside_a_checkout_just_writes(tmp_path):
    await FilePipelineStore(tmp_path / "plain", git_commit=True).save(_pipeline())
    assert (tmp_path / "plain" / "p1.yaml").exists()


def test_export_then_validate_round_trips(tmp_path):
    configs = [
        PipelineBase(id="a", name="A", steps=[{"op": "sort", "by": ["x"], "ascending": False}])
        .model_dump(mode="json"),
        PipelineBase(id="b", name="B", schedule={"cron_expr": "0 1 * * *"}).model_dump(mode="json"),
    ]
    paths, errors = export_pipelines(configs, tmp_path)
    assert errors == []
    assert [p.name for p in paths] == ["a.yaml", "b.yaml"]
    for c, path in zip(configs, paths):
        assert load_pipeline(path).model_dump(mode="json") == c


def test_export_keeps_a_config_that_no_longer_validates(tmp_path):
    bad = {"id": "old", "name": "Old", "steps": [{"op": "gone"}]}
    paths, errors = export_pipelines([bad], tmp_path)
    assert yaml.safe_load(paths[0].read_text()) == bad
    assert errors and errors[0][0] == "old"
    with pytest.raises(ValueError):
        load_pipeline(paths[0])


def test_file_revision_id_is_the_content_hash(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("id: a\nname: A\n")
    r1 = read_revision(path)
    assert (r1.pipeline_id, r1.config["name"]) == ("a", "A")
    assert read_revision(path).id == r1.id
    path.write_text("id: a\nname: A2\n")
    assert read_revision(path).id != r1.id


def test_file_id_must_match_its_name(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("id: b\nname: B\n")
    with pytest.raises(ValueError, match="b"):
        read_revision(path)


def test_file_revision_only_in_file_mode_and_only_for_the_pinned_content(tmp_path, monkeypatch):
    (tmp_path / "a.yaml").write_text("id: a\nname: A\n")
    rid = read_revision(tmp_path / "a.yaml").id
    monkeypatch.setenv("DTE_PIPELINES_DIR", str(tmp_path))
    assert file_revision("a", rid) is None  # postgres mode
    monkeypatch.setenv("DTE_PIPELINE_STORE", "file")
    assert file_revision("a", rid).config["name"] == "A"
    assert file_revision("a", "someotherrev") is None
    assert file_revision("nope", rid) is None


def test_store_flag_picks_the_pipeline_store(tmp_path, monkeypatch):
    from dte.api import deps
    from dte.store.postgres import PostgresPipelineStore

    monkeypatch.setenv("DTE_DATABASE_URL", "postgresql+asyncpg://u:p@localhost:1/none")
    deps._session_factory.cache_clear()
    assert type(deps.get_pipeline_store()) is PostgresPipelineStore
    monkeypatch.setenv("DTE_PIPELINE_STORE", "file")
    monkeypatch.setenv("DTE_PIPELINES_DIR", str(tmp_path))
    monkeypatch.setenv("DTE_PIPELINES_GIT_COMMIT", "true")
    store = deps.get_pipeline_store()
    assert isinstance(store, FilePipelineStore)
    assert (store.root, store._git, type(store._index)) == (tmp_path, True, PostgresPipelineStore)
    deps._session_factory.cache_clear()
