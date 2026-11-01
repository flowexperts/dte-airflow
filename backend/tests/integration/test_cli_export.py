"""Plan 090: `dte export` writes each pipeline's latest revision as YAML,
plus the sources and destinations `dte run` needs."""
import asyncio
import os

import pytest
import yaml

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.getenv("DTE_DATABASE_URL"), reason="requires DTE_DATABASE_URL"),
]

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from dte.cli import main  # noqa: E402
from dte.models.pipeline import (  # noqa: E402
    DestinationBase,
    Pipeline,
    PipelineBase,
    PipelineRevisionBase,
    SourceBase,
)
from dte.store.files import read_revision  # noqa: E402
from dte.store.postgres import (  # noqa: E402
    PostgresDestinationStore,
    PostgresPipelineRevisionStore,
    PostgresPipelineStore,
    PostgresSourceStore,
)


async def _seed(factory, v1, v2):
    await PostgresSourceStore(factory).save(SourceBase(
        id="exp-src", connection_id="local_fs", source_type="filesystem", table="t",
        config={"bucket_url": "/tmp", "file_glob": "*.json"}))
    await PostgresDestinationStore(factory).save(DestinationBase(
        id="exp-dst", connection_id="local_fs", config={"type": "json_file", "path": "/tmp/o.json"}))
    await PostgresPipelineStore(factory).save(Pipeline(**v2.model_dump()))
    revs = PostgresPipelineRevisionStore(factory)
    await revs.save(PipelineRevisionBase(id="exp-r1", pipeline_id=v1.id, config=v1.model_dump(mode="json")))
    await asyncio.sleep(0.01)  # changed_at orders them
    await revs.save(PipelineRevisionBase(id="exp-r2", pipeline_id=v2.id, config=v2.model_dump(mode="json")))


async def _cleanup(factory):
    await PostgresPipelineStore(factory).delete("exp-p")  # cascades revisions
    await PostgresSourceStore(factory).delete("exp-src")
    await PostgresDestinationStore(factory).delete("exp-dst")


def test_export_writes_latest_revision_and_refs(tmp_path):
    engine = create_async_engine(os.environ["DTE_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    v1 = PipelineBase(id="exp-p", name="Export me", sources=["exp-src"], output_id="exp-dst")
    v2 = PipelineBase(id="exp-p", name="Export me", sources=["exp-src"], output_id="exp-dst",
                      steps=[{"op": "filter", "expr": "x > 1"}])
    loop = asyncio.new_event_loop()
    loop.run_until_complete(_cleanup(factory))
    loop.run_until_complete(_seed(factory, v1, v2))
    try:
        main(["export", "--out", str(tmp_path)])
        assert read_revision(tmp_path / "exp-p.yaml").config == v2.model_dump(mode="json")
        assert yaml.safe_load((tmp_path / "sources" / "exp-src.yaml").read_text())["table"] == "t"
        assert yaml.safe_load((tmp_path / "destinations" / "exp-dst.yaml").read_text())["config"]["path"] == "/tmp/o.json"
        assert main(["validate", str(tmp_path / "exp-p.yaml")]) == 0
    finally:
        loop.run_until_complete(_cleanup(factory))
        loop.run_until_complete(engine.dispose())
        loop.close()
