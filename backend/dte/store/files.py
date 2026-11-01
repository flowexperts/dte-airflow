"""Pipelines as files (plan 090): one `<id>.yaml` per pipeline.

The YAML is the model's own `model_dump(mode="json")` and is read back
through the model, so the format follows the model. Reads for the API are
lenient (`Pipeline(**raw)`, like a DB row); `load_pipeline` / `read_revision`
— what `dte validate`, `dte run` and the DAG factory use — are strict
(`PipelineBase`).

A file is its own revision: the revision id is a hash of the file's bytes,
so the DAG tag changes exactly when the file does, with no DB at parse time.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import yaml

from dte.models.pipeline import Pipeline, PipelineBase

log = logging.getLogger(__name__)

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_TIMESTAMPS = {"created_at", "updated_at"}


def dump_yaml(config: dict) -> str:
    return yaml.safe_dump(config, sort_keys=False, allow_unicode=True)


def load_yaml(data: bytes | str) -> dict:
    raw = yaml.safe_load(data)
    if not isinstance(raw, dict):
        raise ValueError("a pipeline file must be a YAML mapping")
    return raw


def load_pipeline(path) -> PipelineBase:
    return PipelineBase.model_validate(load_yaml(Path(path).read_bytes()))


def revision_id(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def read_revision(path) -> SimpleNamespace:
    """The file as a `PipelineRevision`-shaped object (id, pipeline_id, config)."""
    path = Path(path)
    data = path.read_bytes()
    p = PipelineBase.model_validate(load_yaml(data))
    if p.id != path.stem:
        raise ValueError(f"{path.name}: id {p.id!r} does not match the file name")
    return SimpleNamespace(id=revision_id(data), pipeline_id=p.id, config=p.model_dump(mode="json"))


def pipeline_path(pipeline_id: str, root=None) -> Path | None:
    if not SAFE_ID.match(pipeline_id or ""):
        return None
    from dte.config import get_settings

    return Path(root or get_settings().pipelines_dir) / f"{pipeline_id}.yaml"


def file_revision_id(pipeline_id: str) -> str | None:
    """The revision a run of this pipeline pins in file mode: the file as it is now."""
    path = pipeline_path(pipeline_id)
    return revision_id(path.read_bytes()) if path and path.is_file() else None


def file_revision(pipeline_id: str, rev_id: str | None) -> SimpleNamespace | None:
    """In file mode, the pipeline's file when its content is revision `rev_id`.
    None otherwise — including when the file changed since the run was pinned."""
    from dte.config import get_settings

    if get_settings().pipeline_store != "file" or not rev_id:
        return None
    path = pipeline_path(pipeline_id)
    if not (path and path.is_file()):
        return None
    rev = read_revision(path)
    return rev if rev.id == rev_id else None


def export_pipelines(configs: Iterable[dict], out) -> tuple[list[Path], list[tuple[str, str]]]:
    """Write each config as `<out>/<id>.yaml`. A config this build no longer
    validates is still written as-is (losing it would be worse) and reported."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    paths, errors = [], []
    for c in configs:
        try:
            c = PipelineBase.model_validate(c).model_dump(mode="json")
        except ValueError as e:
            errors.append((c.get("id"), str(e)))
        path = out / f"{c['id']}.yaml"
        path.write_text(dump_yaml(c))
        paths.append(path)
    return paths, errors


class FilePipelineStore:
    """`PipelineStore` over a directory. `index`, when given, is another
    `PipelineStore` (Postgres) kept in step so its row exists for list
    pages and for the `pipeline_revisions` foreign key."""

    def __init__(self, root, *, index=None, git_commit: bool = False):
        self.root = Path(root)
        self._index = index
        self._git = git_commit

    def _read(self, path: Path) -> Pipeline:
        p = Pipeline(**load_yaml(path.read_bytes()))
        p.created_at = p.updated_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        return p

    def _rows(self) -> list[Pipeline]:
        rows = []
        for path in self.root.glob("*.yaml"):
            try:
                rows.append(self._read(path))
            except (OSError, ValueError, TypeError, yaml.YAMLError) as e:
                log.warning("skipping unreadable pipeline file %s: %s", path, e)
        return rows

    async def get(self, id: str) -> Pipeline | None:
        path = pipeline_path(id, self.root)
        return self._read(path) if path and path.is_file() else None

    async def save(self, pipeline: Pipeline) -> None:
        path = pipeline_path(pipeline.id, self.root)
        if path is None:
            raise ValueError(f"pipeline id {pipeline.id!r} can't be a file name")
        if self._index is not None:
            await self._index.save(pipeline)  # enforces UNIQUE(name)
        else:
            # ponytail: O(n) scan per save; the Postgres index does this in prod.
            for other in self._rows():
                if other.id != pipeline.id and other.name == pipeline.name:
                    raise ValueError(f"Pipeline name '{pipeline.name}' already exists")
        self.root.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: the dag-processor must never parse half a file.
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(dump_yaml(pipeline.model_dump(mode="json", exclude=_TIMESTAMPS)))
        os.replace(tmp, path)
        self._commit(path, f"dte: save pipeline {pipeline.id}")

    async def list(self, limit: int = 50, offset: int = 0) -> list[Pipeline]:
        rows = sorted(self._rows(), key=lambda p: p.updated_at, reverse=True)
        return rows[offset:offset + limit]

    async def delete(self, id: str) -> bool:
        path = pipeline_path(id, self.root)
        if not (path and path.is_file()):
            return False
        path.unlink()
        if self._index is not None:
            await self._index.delete(id)
        self._commit(path, f"dte: delete pipeline {id}")
        return True

    def _commit(self, path: Path, message: str) -> None:
        """Best effort: the file is already written, so a git failure is
        logged, never raised. Pushing is left to the user or CI."""
        if not self._git:
            return

        def git(*args):
            return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)

        if git("rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
            return
        git("add", "-A", "--", path.name)
        if git("diff", "--cached", "--quiet", "--", path.name).returncode == 0:
            return  # content unchanged
        r = git("commit", "-q", "-m", message, "--", path.name)
        if r.returncode:
            log.warning("git commit of %s failed: %s", path, r.stderr.strip())
