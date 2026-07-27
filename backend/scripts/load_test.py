"""Run a real load-test pipeline against the DTE API.

Usage:
    uv run python backend/scripts/load_test.py --rows 1000000 [--host http://localhost:8001]

Steps performed:
  1. Create a local_fs connection (idempotent — uses /api/connections upsert semantics)
  2. Create a filesystem source pointing at data/load_test/orders.jsonl
  3. Create a json_file destination
  4. Create a pipeline with filter (US+EU) + aggregate (sum(amount) by customer_id)
  5. Trigger it
  6. Poll until terminal, reporting elapsed every 5s
  7. Print final verdict: rows_written, elapsed, status, error
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8001"
HEADERS = {"Content-Type": "application/json"}

# IDs — use load_test_ prefix so they're easy to spot/clean up
CONN_ID = "load_test_local_fs"
SOURCE_ID = "load_test_orders"
DEST_ID = "load_test_output"
PIPELINE_ID = "load_test_pipeline"


def _post(client: httpx.Client, path: str, body: dict, *, allow_409: bool = False) -> dict:
    r = client.post(f"{BASE}{path}", json=body, headers=HEADERS, timeout=30)
    if r.status_code == 409 and allow_409:
        return {}  # already exists — OK for idempotent setup
    r.raise_for_status()
    return r.json()


def _put(client: httpx.Client, path: str, body: dict) -> dict:
    r = client.put(f"{BASE}{path}", json=body, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def _get(client: httpx.Client, path: str) -> dict:
    r = client.get(f"{BASE}{path}", timeout=30)
    r.raise_for_status()
    return r.json()


def setup_resources(client: httpx.Client, jsonl_abs: str, out_abs: str, rows: int) -> None:
    print("=== Setting up resources ===", flush=True)

    # Connection
    try:
        _post(
            client,
            "/api/connections",
            {
                "id": CONN_ID,
                "name": "load_test_local_fs",
                "connection_type": "local_fs",
                "credentials": {},
            },
            allow_409=True,
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            print(f"  Connection {CONN_ID} already exists — reusing", flush=True)
        else:
            raise
    else:
        print(f"  Created connection {CONN_ID}", flush=True)

    # Source — use PUT to upsert
    try:
        _put(
            client,
            f"/api/sources/{SOURCE_ID}",
            {
                "id": SOURCE_ID,
                "name": f"load_test_orders_{rows}",
                "source_type": "filesystem",
                "connection_id": CONN_ID,
                "config": {
                    "bucket_url": str(Path(jsonl_abs).parent),
                    "file_glob": "orders.jsonl",
                    "format": "jsonl",
                },
            },
        )
        print(f"  Upserted source {SOURCE_ID}", flush=True)
    except httpx.HTTPStatusError:
        # Source may not support PUT — try POST
        try:
            _post(
                client,
                "/api/sources",
                {
                    "id": SOURCE_ID,
                    "name": f"load_test_orders_{rows}",
                    "source_type": "filesystem",
                    "connection_id": CONN_ID,
                    "config": {
                        "bucket_url": str(Path(jsonl_abs).parent),
                        "file_glob": "orders.jsonl",
                        "format": "jsonl",
                    },
                },
                allow_409=True,
            )
            print(f"  Created source {SOURCE_ID}", flush=True)
        except httpx.HTTPStatusError as e2:
            if e2.response.status_code == 409:
                print(f"  Source {SOURCE_ID} already exists — reusing", flush=True)
            else:
                raise

    # Destination
    try:
        _post(
            client,
            "/api/destinations",
            {
                "id": DEST_ID,
                "name": "load_test_output",
                "connection_id": CONN_ID,
                "config": {
                    "type": "json_file",
                    "path": out_abs,
                },
            },
            allow_409=True,
        )
        print(f"  Created destination {DEST_ID}", flush=True)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            print(f"  Destination {DEST_ID} already exists — reusing", flush=True)
        else:
            raise

    # Pipeline
    pipeline_body = {
        "id": PIPELINE_ID,
        "name": f"Load test — {rows:,} rows",
        "sources": [SOURCE_ID],
        "output_id": DEST_ID,
        "steps": [
            {
                "op": "filter",
                "expr": "region IN ('US', 'EU')",
            },
            {
                "op": "aggregate",
                "group_by": ["customer_id"],
                "aggregations": [
                    {"field": "amount", "func": "sum", "alias": "total_amount"},
                ],
            },
        ],
    }
    try:
        _post(client, "/api/pipelines", pipeline_body, allow_409=True)
        print(f"  Created pipeline {PIPELINE_ID}", flush=True)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            # Update it so it picks up any config changes
            _put(client, f"/api/pipelines/{PIPELINE_ID}", pipeline_body)
            print(f"  Updated existing pipeline {PIPELINE_ID}", flush=True)
        else:
            raise


def run_pipeline(client: httpx.Client) -> tuple[str, float, dict]:
    print("\n=== Triggering pipeline ===", flush=True)
    t0 = time.perf_counter()
    resp = _post(client, f"/api/pipelines/{PIPELINE_ID}/trigger", {})
    run_id = resp.get("run_id") or resp.get("id")
    if not run_id:
        raise RuntimeError(f"Unexpected trigger response: {resp}")
    print(f"  run_id: {run_id}", flush=True)

    # Poll until terminal
    print("  Polling...", flush=True)
    last_status = None
    while True:
        run = _get(client, f"/api/runs/{run_id}")
        status = run.get("status")
        if status != last_status:
            elapsed = time.perf_counter() - t0
            print(f"  [{elapsed:.1f}s] status={status}", flush=True)
            last_status = status
        if status in ("completed", "failed", "completed_with_warnings", "failed_quality"):
            elapsed = time.perf_counter() - t0
            return run_id, elapsed, run
        time.sleep(5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--host", default="http://localhost:8001")
    args = parser.parse_args()

    global BASE
    BASE = args.host

    script_dir = Path(__file__).parent
    repo_root = script_dir.parent.parent
    jsonl_abs = str(repo_root / "data" / "load_test" / "orders.jsonl")
    out_abs = str(repo_root / "data" / "load_test" / "output.json")

    if not Path(jsonl_abs).exists():
        print(
            f"ERROR: {jsonl_abs} not found.\n"
            "Run: uv run python backend/scripts/gen_load_fixture.py --rows {args.rows}",
            file=sys.stderr,
        )
        sys.exit(1)

    file_mb = Path(jsonl_abs).stat().st_size / 1024 / 1024
    print(f"Input file: {jsonl_abs} ({file_mb:.0f} MB)", flush=True)

    with httpx.Client(timeout=60) as client:
        # Verify API is up
        r = client.get(f"{BASE}/healthz")
        if r.status_code != 200:
            print(f"ERROR: /healthz returned {r.status_code}", file=sys.stderr)
            sys.exit(1)
        print(f"API healthy at {BASE}", flush=True)

        setup_resources(client, jsonl_abs, out_abs, args.rows)
        run_id, elapsed, run = run_pipeline(client)

    print("\n=== RESULT ===", flush=True)
    print(f"  run_id:       {run_id}")
    print(f"  status:       {run.get('status')}")
    print(f"  rows_written: {run.get('rows_written')}")
    print(f"  elapsed:      {elapsed:.1f}s")
    if run.get("error"):
        print(f"  error:        {run['error']}")
    print(f"  finished_at:  {run.get('finished_at')}")


if __name__ == "__main__":
    main()
