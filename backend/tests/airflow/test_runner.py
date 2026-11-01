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


def _with_contracts(p, *contracts):
    return Pipeline(**{**p.model_dump(), "quality_contracts": list(contracts)})


def test_failing_pre_contract_leaves_destination_untouched(tmp_path):
    """Plan 086: a blocking contract runs on the compiled result before the
    write, so a rejected run never overwrites the destination."""
    p, srcs, dest, out = _setup(tmp_path)
    out.write_text("previous")
    p = _with_contracts(p, {"type": "row_count_between", "id": "rc", "min": 5, "max": 9})
    res = run_pipeline(p, srcs, dest)
    assert res.status == "failed_quality" and res.rows_written == 0
    assert out.read_text() == "previous"
    assert res.quality[0]["passed"] is False


def test_warning_pre_contract_still_writes(tmp_path):
    p, srcs, dest, out = _setup(tmp_path)
    p = _with_contracts(p, {"type": "row_count_between", "id": "rc", "min": 5, "max": 9, "severity": "warn"})
    res = run_pipeline(p, srcs, dest)
    assert res.status == "completed_with_warnings" and res.rows_written == 2
    assert len(json.loads(out.read_text())) == 2


def test_post_contract_reads_the_written_destination(tmp_path):
    p, srcs, dest, out = _setup(tmp_path)
    p = _with_contracts(
        p,
        {"type": "column_not_null", "id": "pre", "column": "age"},
        {"type": "row_count_between", "id": "post", "min": 2, "max": 2, "phase": "post"},
    )
    res = run_pipeline(p, srcs, dest)
    assert res.status == "completed" and res.rows_written == 2
    assert [q["contract_id"] for q in res.quality] == ["pre", "post"]


def test_saved_contract_without_phase_reads_as_pre():
    from pydantic import TypeAdapter

    from dte.models.quality import Contract
    c = TypeAdapter(Contract).validate_python({"type": "column_unique", "id": "u", "column": "x"})
    assert c.phase == "pre"
