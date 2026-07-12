import pytest
import json
from pathlib import Path
from fastapi.testclient import TestClient
from dte.engine.duckdb_engine import DuckDBEngine
from dte.compiler.ibis_compiler import compile_pipeline
from dte.models.pipeline import Pipeline, DltSource
from dte.sources.dlt_loader import load_source


def make_pipeline_dict(sources, steps, output_path, output_fields=None):
    out = {"type": "json_file", "path": output_path}
    if output_fields:
        out["fields"] = output_fields
    return {
        "id": "p1", "name": "integration_test",
        "sources": sources,
        "steps": steps,
        "output": out,
    }


def _dlt_source(src_id: str, tmp_path: Path, file_glob: str, table: str) -> dict:
    return {
        "id": src_id,
        "source_type": "filesystem",
        "config": {"bucket_url": str(tmp_path), "file_glob": file_glob},
        "table": table,
    }


def test_end_to_end_filter_rename(tmp_path):
    data = [
        {"first_name": "alice", "age": 30},
        {"first_name": "bob", "age": 16},
        {"first_name": "carol", "age": 22},
    ]
    src_file = tmp_path / "input.json"
    src_file.write_text(json.dumps(data))
    out = tmp_path / "output.json"

    pipeline_dict = make_pipeline_dict(
        sources=[_dlt_source("src", tmp_path, "input.json", "input")],
        steps=[
            {"op": "filter", "expr": "age >= 18"},
            {"op": "rename", "mappings": {"first_name": "name"}},
        ],
        output_path=str(out),
    )
    pipeline = Pipeline(**pipeline_dict)
    engine = DuckDBEngine()
    src = DltSource(**pipeline_dict["sources"][0])
    tables = {"src": load_source(src, engine.con)}
    compiled = compile_pipeline(pipeline, tables)
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
    src_file = tmp_path / "orders.json"
    src_file.write_text(json.dumps(data))
    out = tmp_path / "agg_output.json"

    pipeline_dict = make_pipeline_dict(
        sources=[_dlt_source("src", tmp_path, "orders.json", "orders")],
        steps=[{
            "op": "aggregate",
            "group_by": ["order.category"],
            "aggregations": [{"field": "order.amount", "func": "sum", "alias": "total"}]
        }],
        output_path=str(out),
    )
    pipeline = Pipeline(**pipeline_dict)
    engine = DuckDBEngine()
    src = DltSource(**pipeline_dict["sources"][0])
    tables = {"src": load_source(src, engine.con)}
    compiled = compile_pipeline(pipeline, tables)
    rows = engine.execute_to_json(compiled, str(out))

    assert rows == 2
    result = json.loads(out.read_text())
    # dlt normalizes nested keys with __ separator
    key = "order__category" if "order__category" in result[0] else "order.category"
    categories = {r[key]: r["total"] for r in result}
    assert categories["electronics"] == 300
    assert categories["clothing"] == 50


def test_api_trigger_and_poll(tmp_path):
    from dte.api.main import app
    from dte.api.deps import get_pipeline_store, get_run_store
    from dte.store.memory import MemoryPipelineStore, MemoryRunStore

    p_store = MemoryPipelineStore()
    r_store = MemoryRunStore()
    app.dependency_overrides[get_pipeline_store] = lambda: p_store
    app.dependency_overrides[get_run_store] = lambda: r_store

    data = [
        {"name": "alice", "score": 90},
        {"name": "bob", "score": 45},
    ]
    src_file = tmp_path / "scores.json"
    src_file.write_text(json.dumps(data))
    out = tmp_path / "api_out.json"

    pipeline_payload = {
        "id": "api-p1",
        "name": "api_test",
        "sources": [_dlt_source("src", tmp_path, "scores.json", "scores")],
        "steps": [{"op": "filter", "expr": "score > 50"}],
        "output": {"type": "json_file", "path": str(out)},
    }

    client = TestClient(app)

    r = client.post("/api/pipelines", json=pipeline_payload)
    assert r.status_code == 200
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

    assert r.json()["status"] == "completed"
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

    pipeline_dict = make_pipeline_dict(
        sources=[
            _dlt_source("users", tmp_path, "users.json", "users"),
            _dlt_source("orders", tmp_path, "orders.json", "orders"),
        ],
        steps=[{
            "op": "join",
            "left": "users",
            "right": "orders",
            "on": "id",
            "how": "inner",
            "output_id": "joined",
        }],
        output_path=str(out),
    )
    pipeline = Pipeline(**pipeline_dict)
    engine = DuckDBEngine()
    tables = {}
    for src_dict in pipeline_dict["sources"]:
        src = DltSource(**src_dict)
        tables[src.id] = load_source(src, engine.con)

    compiled = compile_pipeline(pipeline, tables)
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

    pipeline_dict = make_pipeline_dict(
        sources=[_dlt_source("src", tmp_path, "sales.json", "sales")],
        steps=[{
            "op": "pivot",
            "index": "region",
            "columns": "product",
            "values": "sales",
            "agg": "sum",
        }],
        output_path=str(out),
    )
    pipeline = Pipeline(**pipeline_dict)
    engine = DuckDBEngine()
    src = DltSource(**pipeline_dict["sources"][0])
    tables = {"src": load_source(src, engine.con)}
    compiled = compile_pipeline(pipeline, tables)
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

    pipeline_dict = make_pipeline_dict(
        sources=[_dlt_source("src", tmp_path, "users.json", "users")],
        steps=[{"op": "select", "drop": ["ssn"]}],
        output_path=str(out),
    )
    pipeline = Pipeline(**pipeline_dict)
    engine = DuckDBEngine()
    src = DltSource(**pipeline_dict["sources"][0])
    tables = {"src": load_source(src, engine.con)}
    compiled = compile_pipeline(pipeline, tables)
    engine.execute_to_json(compiled, str(out))

    result = json.loads(out.read_text())
    for row in result:
        assert "ssn" not in row
        # drop is schema-adaptive: everything not named `ssn` survives, even
        # columns we never enumerated (email, phone).
        assert set(row.keys()) >= {"id", "name", "email", "phone"}
