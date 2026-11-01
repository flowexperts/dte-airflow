"""`http_lookup` compiles to a cached, per-row GET (plan 085)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ibis
import pandas as pd
import pytest

from dte.compiler.ibis_compiler import compile_pipeline
from dte.engine.duckdb_engine import DuckDBEngine
from dte.errors import CompilerError
from dte.models.pipeline import Pipeline

PACKAGES = {
    "requests": {
        "info": {"summary": "HTTP for Humans", "yanked": False,
                 "project_urls": {"Source": "https://github.com/psf/requests"}},
        "releases": {"1.0": [{"upload_time": "2011-02-14T08:49:42"}],
                     "2.0": [{"upload_time": "2026-05-14T19:25:27"}]},
        "score": 0.5,
    },
    "a b": {"info": {"summary": "space", "yanked": True, "project_urls": None},
            "releases": {"0.1": [{"upload_time": "2026-10-30T00:00:00"}]}, "score": 1.5},
}


@pytest.fixture
def api():
    """`/pypi/<name>/json`; `boom` → 500; unknown → 404. Records every path."""
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            from urllib.parse import unquote
            name = unquote(self.path.split("/")[2])
            if name == "boom":
                code, body = 500, {"error": "down"}
            elif name in PACKAGES:
                code, body = 200, PACKAGES[name]
            else:
                code, body = 404, {"message": "Not Found"}
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", hits
    server.shutdown()


FIELDS = [
    {"name": "summary", "path": "info.summary", "type": "string"},
    {"name": "repo", "path": "info.project_urls.Source", "type": "string"},
    {"name": "releases", "path": "length(keys(releases))", "type": "int"},
    {"name": "score", "path": "score", "type": "float"},
    {"name": "yanked", "path": "info.yanked", "type": "boolean"},
    {"name": "last_upload", "path": "max(values(releases)[][].upload_time)", "type": "timestamp"},
]


def _run(base, names, **step_over):
    engine = DuckDBEngine()
    engine.con.create_table("pkgs", ibis.memtable({"name": names}).to_pyarrow())
    step = {"op": "http_lookup", "url": base + "/pypi/{name}/json", "fields": FIELDS}
    step.update(step_over)
    pipeline = Pipeline(id="p", name="p", sources=["pkgs"], output_id="o", steps=[step])
    out = compile_pipeline(pipeline, {"pkgs": engine.con.table("pkgs")}, engine=engine)
    df = out.execute()
    return out, {r["name"]: r for r in df.to_dict("records")}


def test_fields_become_typed_columns(api):
    base, hits = api
    out, rows = _run(base, ["requests"])
    r = rows["requests"]
    assert r["summary"] == "HTTP for Humans"
    assert r["repo"] == "https://github.com/psf/requests"
    assert r["releases"] == 2
    assert r["score"] == 0.5
    assert bool(r["yanked"]) is False
    assert str(r["last_upload"]).startswith("2026-05-14 19:25:27")
    schema = out.schema()
    assert schema["releases"].is_integer()
    assert schema["score"].is_floating()
    assert schema["yanked"].is_boolean()
    assert schema["last_upload"].is_timestamp()
    meta = json.loads(r["http_meta"])
    assert meta["status"] == 200 and meta["cached"] is False


def test_values_are_url_encoded(api):
    base, hits = api
    _, rows = _run(base, ["a b"])
    assert hits == ["/pypi/a%20b/json"]
    assert rows["a b"]["summary"] == "space"
    assert pd.isna(rows["a b"]["repo"])


def test_404_is_a_result_with_null_fields_and_is_cached(api):
    base, hits = api
    _, rows = _run(base, ["gone"])
    r = rows["gone"]
    assert pd.isna(r["summary"]) and pd.isna(r["releases"])
    assert json.loads(r["http_meta"])["status"] == 404
    _run(base, ["gone"])
    assert len(hits) == 1


def test_server_error_is_not_cached(api):
    base, hits = api
    _, rows = _run(base, ["boom"])
    meta = json.loads(rows["boom"]["http_meta"])
    assert meta["status"] == 500 and meta["error"]
    _run(base, ["boom"])
    assert len(hits) == 2


def test_success_is_cached_for_the_day(api):
    base, hits = api
    _run(base, ["requests"])
    _, rows = _run(base, ["requests"])
    assert len(hits) == 1
    assert json.loads(rows["requests"]["http_meta"])["cached"] is True
    assert rows["requests"]["releases"] == 2


def test_max_rows_guard_fires_before_any_request(api):
    base, hits = api
    with pytest.raises(CompilerError, match="max_rows"):
        _run(base, ["requests", "a b", "x"], max_rows=2)
    assert hits == []


def test_on_error_fail_raises(api):
    base, _ = api
    with pytest.raises(CompilerError, match="500"):
        _run(base, ["boom"], on_error="fail")


def test_connection_supplies_headers(api, monkeypatch):
    from dte.airflow import connections

    seen = {}
    monkeypatch.setattr(connections, "http_headers",
                        lambda cid: seen.setdefault(cid, {"Authorization": "Bearer t"}))
    base, _ = api
    _run(base, ["requests"], connection_id="gh")
    assert seen == {"gh": {"Authorization": "Bearer t"}}


def test_url_column_must_exist(api):
    base, hits = api
    with pytest.raises(CompilerError, match="nope"):
        _run(base, ["requests"], url=base + "/pypi/{nope}/json")
    assert hits == []


def test_two_lookups_keep_separate_meta(api):
    """The squat scan chains two lookups (PyPI, then pypistats); one shared
    `http_meta` column let the second overwrite the first's status."""
    base, _ = api
    engine = DuckDBEngine()
    engine.con.create_table("pkgs", ibis.memtable({"name": ["requests"]}).to_pyarrow())
    steps = [
        {"op": "http_lookup", "url": base + "/pypi/{name}/json",
         "fields": [FIELDS[0]]},
        {"op": "http_lookup", "url": base + "/pypi/missing-{name}/json",
         "fields": [{"name": "other", "path": "info.summary", "type": "string"}],
         "meta_field": "stats_meta"},
    ]
    pipeline = Pipeline(id="p", name="p", sources=["pkgs"], output_id="o", steps=steps)
    row = compile_pipeline(pipeline, {"pkgs": engine.con.table("pkgs")}, engine=engine).execute().iloc[0]
    assert json.loads(row["http_meta"])["status"] == 200
    assert json.loads(row["stats_meta"])["status"] == 404


def test_meta_field_must_not_clash_with_a_field():
    from pydantic import ValidationError

    from dte.models.pipeline import HttpLookupStep

    with pytest.raises(ValidationError, match="meta_field"):
        HttpLookupStep.model_validate({
            "op": "http_lookup", "url": "http://x/{name}", "meta_field": "summary",
            "fields": [FIELDS[0]],
        })
