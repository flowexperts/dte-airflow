"""`load_source(..., sample=N)` bounds the work for eager sources (plan 084).

rest_api and mongodb copy the whole source into DuckDB before anything can
read it, so a 20-row preview of a paginated API used to fetch every page.
"""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import ibis
import pytest

from dte.models.pipeline import Source
from dte.sources import loader
from dte.sources.loader import load_source

PAGES, PER_PAGE = 50, 10


@pytest.fixture
def paged_api():
    """`GET /items?page=N` → PER_PAGE rows for N <= PAGES, then empty."""
    served: list[int] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            page = int(parse_qs(urlparse(self.path).query).get("page", ["1"])[0])
            served.append(page)
            rows = [] if page > PAGES else [
                {"id": (page - 1) * PER_PAGE + i, "page": page} for i in range(PER_PAGE)
            ]
            body = json.dumps({"data": rows}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/", served
    server.shutdown()


def _rest_source(base_url: str) -> Source:
    return Source(
        id="paged", connection_id="local_fs", source_type="rest_api", table="items",
        config={
            "client": {
                "base_url": base_url,
                "paginator": {"type": "page_number", "base_page": 1, "total_path": None},
            },
            "resources": [{"name": "items", "endpoint": {"path": "items", "data_selector": "data"}}],
        },
    )


def test_rest_api_without_sample_reads_every_page(paged_api):
    base_url, served = paged_api
    df = load_source(_rest_source(base_url), ibis.duckdb.connect(), {}).execute()
    assert len(df) == PAGES * PER_PAGE


def test_rest_api_sample_stops_paginating(paged_api):
    base_url, served = paged_api
    df = load_source(_rest_source(base_url), ibis.duckdb.connect(), {}, sample=15).execute()
    # dlt counts rows per page and does not trim the last one: 2 pages.
    assert 15 <= len(df) <= 2 * PER_PAGE
    assert len(served) <= 3


def test_concurrent_loads_of_one_source_do_not_collide(paged_api):
    """Interactive work runs in threads now, so one source can be loading
    twice at once. dlt's default pipelines_dir keys state by pipeline name,
    and two loads sharing it deleted each other's load packages."""
    base_url, _ = paged_api

    def go(_):
        return len(load_source(_rest_source(base_url), ibis.duckdb.connect(), {}, sample=15).execute())

    with ThreadPoolExecutor(4) as pool:
        assert all(n >= 15 for n in pool.map(go, range(8)))


def test_mongodb_sample_limits_the_cursor(monkeypatch):
    import mongomock

    client = mongomock.MongoClient()
    client["db"]["c"].insert_many([{"n": i} for i in range(100)])
    monkeypatch.setattr(loader, "_mongo_client", lambda url: client)
    src = Source(
        id="m", connection_id="local_fs", source_type="mongodb", table="m",
        config={"database": "db", "collection": "c"},
    )
    df = load_source(src, ibis.duckdb.connect(), {"url": "mongodb://x"}, sample=7).execute()
    assert len(df) == 7


def test_sample_is_ignored_by_lazy_sources(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps([{"x": i} for i in range(30)]))
    src = Source(
        id="f", connection_id="local_fs", source_type="filesystem", table="f",
        config={"bucket_url": str(tmp_path), "file_glob": "a.json"},
    )
    assert len(load_source(src, ibis.duckdb.connect(), {}, sample=5).execute()) == 30
