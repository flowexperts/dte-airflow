import pytest
import json
from pathlib import Path
from fastapi.testclient import TestClient
from dte.engine.duckdb_engine import DuckDBEngine
from dte.compiler.ibis_compiler import compile_pipeline
from dte.models.pipeline import Pipeline, Source, Destination, DestinationCreate, JsonFileTarget
from dte.sources.loader import load_source

pytestmark = pytest.mark.integration


def make_pipeline(source_ids, steps, output_id="out1"):
    return Pipeline(
        id="p1", name="integration_test",
        sources=source_ids, steps=steps, output_id=output_id,
    )


def _fs_source(src_id: str, tmp_path: Path, file_glob: str, table: str, connection_id: str = "local_fs") -> Source:
    return Source(
        id=src_id,
        connection_id=connection_id,
        source_type="filesystem",
        config={"bucket_url": str(tmp_path), "file_glob": file_glob},
        table=table,
    )


def _json_dest(dest_id: str, connection_id: str, out_path: Path, fields=None) -> DestinationCreate:
    """Return a DestinationCreate so Pydantic validators run and config is typed."""
    cfg = {"type": "json_file", "path": str(out_path)}
    if fields:
        cfg["fields"] = fields
    return DestinationCreate(id=dest_id, connection_id=connection_id, config=cfg)


def test_end_to_end_filter_rename(tmp_path):
    data = [
        {"first_name": "alice", "age": 30},
        {"first_name": "bob", "age": 16},
        {"first_name": "carol", "age": 22},
    ]
    (tmp_path / "input.json").write_text(json.dumps(data))
    out = tmp_path / "output.json"

    src = _fs_source("src", tmp_path, "input.json", "input")
    dest = _json_dest("out1", "local_fs", out)
    pipeline = make_pipeline(["src"], [
        {"op": "filter", "expr": "age >= 18"},
        {"op": "rename", "mappings": {"first_name": "name"}},
    ])
    engine = DuckDBEngine()
    tables = {"src": load_source(src, engine.con, {})}
    compiled = compile_pipeline(pipeline, tables, output=dest.config)
    rows = engine.execute_to_json(compiled, str(out))

    assert rows == 2
    result = json.loads(out.read_text())
    names = [r["name"] for r in result]
    assert "alice" in names
    assert "carol" in names
    assert "bob" not in names


def test_end_to_end_nested_json_flatten_aggregate(tmp_path):
    data = [
        {"order": {"category": "electronics", "amount": 100}},
        {"order": {"category": "electronics", "amount": 200}},
        {"order": {"category": "clothing", "amount": 50}},
    ]
    (tmp_path / "orders.json").write_text(json.dumps(data))
    out = tmp_path / "agg_output.json"

    src = _fs_source("src", tmp_path, "orders.json", "orders")
    dest = _json_dest("out1", "local_fs", out)
    pipeline = make_pipeline(["src"], [{
        "op": "aggregate",
        "group_by": ["order.category"],
        "aggregations": [{"field": "order.amount", "func": "sum", "alias": "total"}]
    }])
    engine = DuckDBEngine()
    tables = {"src": load_source(src, engine.con, {})}
    compiled = compile_pipeline(pipeline, tables, output=dest.config)
    rows = engine.execute_to_json(compiled, str(out))

    assert rows == 2
    result = json.loads(out.read_text())
    key = "order__category" if "order__category" in result[0] else "order.category"
    categories = {r[key]: r["total"] for r in result}
    assert categories["electronics"] == 300
    assert categories["clothing"] == 50


def test_api_trigger_and_poll(tmp_path):
    from dte.api.main import app
    from dte.api.deps import (
        get_pipeline_store, get_run_store,
        get_source_store, get_destination_store,
    )
    from tests.fakes import (
        FakePipelineStore, FakeRunStore,
        FakeSourceStore, FakeDestinationStore,
    )

    p_store = FakePipelineStore()
    r_store = FakeRunStore()
    s_store = FakeSourceStore()
    d_store = FakeDestinationStore()
    app.dependency_overrides[get_pipeline_store] = lambda: p_store
    app.dependency_overrides[get_run_store] = lambda: r_store
    app.dependency_overrides[get_source_store] = lambda: s_store
    app.dependency_overrides[get_destination_store] = lambda: d_store

    data = [
        {"name": "alice", "score": 90},
        {"name": "bob", "score": 45},
    ]
    (tmp_path / "scores.json").write_text(json.dumps(data))
    out = tmp_path / "api_out.json"

    # Seed source + destination stores.
    import asyncio
    src = _fs_source("src", tmp_path, "scores.json", "scores")
    dest = _json_dest("out1", "local_fs", out)
    asyncio.get_event_loop().run_until_complete(s_store.save(src))
    asyncio.get_event_loop().run_until_complete(d_store.save(dest))

    pipeline_payload = {
        "id": "api-p1",
        "name": "api_test",
        "sources": ["src"],
        "steps": [{"op": "filter", "expr": "score > 50"}],
        "output_id": "out1",
    }

    client = TestClient(app)

    r = client.post("/api/pipelines", json=pipeline_payload)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert pid == "api-p1"

    r = client.get(f"/api/pipelines/{pid}")
    assert r.status_code == 200
    assert r.json()["name"] == "api_test"

    r = client.post(f"/api/pipelines/{pid}/trigger")
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    import time
    for _ in range(20):
        r = client.get(f"/api/runs/{run_id}")
        assert r.status_code == 200
        status = r.json()["status"]
        if status in ("completed", "failed"):
            break
        time.sleep(0.1)

    assert r.json()["status"] == "completed", r.json()
    assert r.json()["rows_written"] == 1
    result = json.loads(out.read_text())
    assert result[0]["name"] == "alice"
    app.dependency_overrides.clear()


def test_end_to_end_join_two_sources(tmp_path):
    users_data = [
        {"id": 1, "name": "alice"},
        {"id": 2, "name": "bob"},
        {"id": 3, "name": "carol"},
    ]
    orders_data = [
        {"id": 1, "amount": 100},
        {"id": 2, "amount": 200},
        {"id": 4, "amount": 50},
    ]
    (tmp_path / "users.json").write_text(json.dumps(users_data))
    (tmp_path / "orders.json").write_text(json.dumps(orders_data))
    out = tmp_path / "joined_output.json"

    users_src = _fs_source("users", tmp_path, "users.json", "users")
    orders_src = _fs_source("orders", tmp_path, "orders.json", "orders")
    dest = _json_dest("out1", "local_fs", out)
    pipeline = make_pipeline(["users", "orders"], [{
        "op": "join",
        "left": "users",
        "right": "orders",
        "on": "id",
        "how": "inner",
        "output_id": "joined",
    }])
    engine = DuckDBEngine()
    tables = {
        "users": load_source(users_src, engine.con, {}),
        "orders": load_source(orders_src, engine.con, {}),
    }
    compiled = compile_pipeline(pipeline, tables, output=dest.config)
    df = compiled.execute()

    assert len(df) == 2
    assert "name" in df.columns
    assert "amount" in df.columns
    names = set(df["name"].tolist())
    assert "alice" in names
    assert "bob" in names
    assert "carol" not in names


def test_end_to_end_pivot(tmp_path):
    sales_data = [
        {"region": "East", "product": "A", "sales": 100},
        {"region": "East", "product": "B", "sales": 150},
        {"region": "West", "product": "A", "sales": 200},
        {"region": "West", "product": "B", "sales": 50},
    ]
    (tmp_path / "sales.json").write_text(json.dumps(sales_data))
    out = tmp_path / "pivot_output.json"

    src = _fs_source("src", tmp_path, "sales.json", "sales")
    dest = _json_dest("out1", "local_fs", out)
    pipeline = make_pipeline(["src"], [{
        "op": "pivot",
        "index": "region",
        "columns": "product",
        "values": "sales",
        "agg": "sum",
    }])
    engine = DuckDBEngine()
    tables = {"src": load_source(src, engine.con, {})}
    compiled = compile_pipeline(pipeline, tables, output=dest.config)
    df = compiled.execute()

    assert "A" in df.columns
    assert "B" in df.columns
    assert "region" in df.columns
    east_row = df[df["region"] == "East"]
    assert east_row["A"].iloc[0] == 100
    assert east_row["B"].iloc[0] == 150


def test_select_drop_step_passes_new_columns_through(tmp_path):
    data = [
        {"id": 1, "name": "alice", "ssn": "111", "email": "a@x", "phone": "555"},
        {"id": 2, "name": "bob", "ssn": "222", "email": "b@x", "phone": "666"},
    ]
    (tmp_path / "users.json").write_text(json.dumps(data))
    out = tmp_path / "out.json"

    src = _fs_source("src", tmp_path, "users.json", "users")
    dest = _json_dest("out1", "local_fs", out)
    pipeline = make_pipeline(["src"], [{"op": "select", "drop": ["ssn"]}])
    engine = DuckDBEngine()
    tables = {"src": load_source(src, engine.con, {})}
    compiled = compile_pipeline(pipeline, tables, output=dest.config)
    engine.execute_to_json(compiled, str(out))

    result = json.loads(out.read_text())
    for row in result:
        assert "ssn" not in row
        assert set(row.keys()) >= {"id", "name", "email", "phone"}
