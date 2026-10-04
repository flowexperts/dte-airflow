"""run_pipeline with no stores: local_fs transform, failing/warning quality."""
import json

from dte.airflow.runner import run_pipeline
from dte.models.pipeline import Connection, Destination, Pipeline, Source, SourceTableRef


def _setup(tmp_path, ptype="transform", steps=()):
    (tmp_path / "in.json").write_text(json.dumps([{"age": 5}, {"age": 30}]))
    conn = Connection(id="local_fs", connection_type="local_fs", credentials={})
    src = Source(id="s1", connection_id="local_fs", source_type="filesystem",
                 config={"bucket_url": str(tmp_path), "file_glob": "in.json"},
                 table="t", format="json")
    ref = SourceTableRef(source_id="s1", alias="s1")
    out = tmp_path / "out.json"
    dest = Destination(id="d1", connection_id="local_fs", dest_type="json_file",
                       config={"type": "json_file", "path": str(out)})
    dest.narrow_config()
    p = Pipeline(id="p1", name="p1", sources=[ref.model_dump()], steps=list(steps),
                 output_id="d1", pipeline_type=ptype)
    return p, [(ref, src, conn, {})], (dest, {}), out


def test_transform_writes_output(tmp_path):
    p, srcs, dest, out = _setup(tmp_path, steps=[{"op": "filter", "expr": "age > 18"}])
    res = run_pipeline(p, srcs, dest)
    assert res.status == "completed" and res.rows_written == 1
    assert json.loads(out.read_text()) == [{"age": 30}]


def test_quality_fail_and_warn(tmp_path):
    for sev, status in (("fail", "failed_quality"), ("warn", "completed_with_warnings")):
        p, srcs, _, _ = _setup(tmp_path, "quality", [{"op": "check", "expr": "age > 18", "severity": sev, "label": "adult"}])
        res = run_pipeline(p, srcs)
        assert res.status == status and res.quality
