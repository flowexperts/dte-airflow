"""The `dte` command.

    dte db upgrade                      migrate DTE's `dte` schema
    dte validate <file>...              load each pipeline file with the typed model (CI)
    dte run <file> [--sample N]         run a pipeline file locally, no Postgres (plan 090)
    dte export [--out DIR]              DB -> files, for the one-time move to files
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path


def db_upgrade() -> None:
    from alembic.config import Config

    from alembic import command
    from dte.airflow.db import sync_url

    # Installed wheel: dte/migrations. Repo checkout and the image: backend/.
    packaged = Path(__file__).resolve().parent / "migrations"
    root = Path(os.getenv("DTE_ALEMBIC_DIR") or (packaged if packaged.is_dir() else Path(__file__).resolve().parents[1]))
    # alembic/env.py reads DTE_DATABASE_URL as a *sync* URL.
    os.environ["DTE_DATABASE_URL"] = sync_url()
    command.upgrade(Config(str(root / "alembic.ini")), "head")


def validate(files: list[str]) -> int:
    from dte.store.files import read_revision

    failed = 0
    for f in files:
        try:
            read_revision(f)  # what the DAG factory does with it
            print(f"ok  {f}")
        except Exception as e:
            failed += 1
            print(f"FAIL {f}: {e}")
    return 1 if failed else 0


def run(file: str, sample: int | None, refs: str | None) -> int:
    """Sources and the destination are `<refs>/sources/<id>.yaml` and
    `<refs>/destinations/<id>.yaml` (what `dte export` writes; default: the
    file's directory). Their connections come from Airflow (`AIRFLOW_CONN_*`)."""
    from dte.airflow.connections import to_dte
    from dte.airflow.runner import run_pipeline
    from dte.models.pipeline import (
        Destination,
        DestinationBase,
        Pipeline,
        Source,
        SourceBase,
        coerce_source_refs,
    )
    from dte.store.files import load_pipeline, load_yaml

    root = Path(refs or Path(file).parent)

    def ref(kind, model, id):
        return model.model_validate(load_yaml((root / kind / f"{id}.yaml").read_bytes())).model_dump()

    pipeline = Pipeline(**load_pipeline(file).model_dump())
    sources = []
    for r in coerce_source_refs(pipeline.sources):
        src = Source(**ref("sources", SourceBase, r.source_id))
        sources.append((r, src, *to_dte(src.connection_id)))
    destination = None
    if (pipeline.pipeline_type or "transform") == "transform":
        dest = Destination(**ref("destinations", DestinationBase, pipeline.output_id))
        dest.narrow_config()
        destination = (dest, to_dte(dest.connection_id)[1])
    if sample:
        os.environ["DTE_RUN_MAX_ROWS"] = str(sample)  # runner caps output rows from settings
    res = run_pipeline(pipeline, sources, destination)
    print(json.dumps(asdict(res), default=str, indent=2))
    return 1 if res.status == "failed_quality" else 0


def export(out: str) -> int:
    """Latest revision of every pipeline -> `<out>/<id>.yaml`, plus the
    sources and destinations they name, so `dte run` works on the result."""
    from sqlmodel import Session, select

    from dte.airflow.dag_factory import _latest_revisions
    from dte.airflow.db import sync_engine
    from dte.models.pipeline import Destination, Source
    from dte.store.files import dump_yaml, export_pipelines

    paths, errors = export_pipelines([r.config for r in _latest_revisions()[0]], out)
    with Session(sync_engine()) as s:
        for kind, model in (("sources", Source), ("destinations", Destination)):
            (Path(out) / kind).mkdir(parents=True, exist_ok=True)
            for row in s.exec(select(model)).all():
                data = row.model_dump(mode="json", exclude={"created_at", "updated_at"})
                (Path(out) / kind / f"{row.id}.yaml").write_text(dump_yaml(data))
    print(f"exported {len(paths)} pipelines to {out}")
    for pid, err in errors:
        print(f"WARN {pid}: written as-is, does not validate: {err}")
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dte")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("db").add_argument("action", choices=["upgrade"])
    sub.add_parser("validate").add_argument("files", nargs="+")
    r = sub.add_parser("run")
    r.add_argument("file")
    r.add_argument("--sample", type=int, help="cap the rows written")
    r.add_argument("--refs", help="dir holding sources/ and destinations/ (default: the file's dir)")
    sub.add_parser("export").add_argument("--out", default="pipelines")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    if a.cmd == "db":
        db_upgrade()
        return 0
    if a.cmd == "validate":
        return validate(a.files)
    if a.cmd == "run":
        return run(a.file, a.sample, a.refs)
    return export(a.out)
