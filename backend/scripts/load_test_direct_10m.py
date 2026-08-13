"""Direct DuckDB load test — 10M rows.

Variant of load_test_direct.py that accepts an explicit --file argument
so we can point it at orders_10m.jsonl.

Usage:
    uv run python backend/scripts/load_test_direct_10m.py
"""
from __future__ import annotations

import gc
import os
import resource
import time
import tracemalloc
from pathlib import Path

import ibis

WORKTREE = Path(__file__).parent.parent.parent   # worktrees/load-test-runbook/


def rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if os.uname().sysname == "Darwin":
        return usage / 1024 / 1024
    return usage / 1024


def run_test(jsonl_path: Path, out_path: Path, label: str) -> dict:
    gc.collect()
    tracemalloc.start()
    rss_before = rss_mb()
    t0 = time.perf_counter()

    print(f"\n=== {label} ===", flush=True)
    file_mb = jsonl_path.stat().st_size / 1024 / 1024
    print(f"  Input: {jsonl_path.name}  ({file_mb:.0f} MB)", flush=True)

    con = ibis.duckdb.connect()
    native = con.con

    t1 = time.perf_counter()
    native.execute(f"""
        CREATE OR REPLACE VIEW _load_input AS
        SELECT * FROM read_json_auto('{jsonl_path}', maximum_object_size=10485760)
    """)
    source_table = con.table("_load_input")
    t2 = time.perf_counter()
    print(f"  [view created in {t2-t1:.3f}s]", flush=True)

    # Filter
    con.create_view("_filter_input", source_table, overwrite=True)
    filtered = con.sql("SELECT * FROM _filter_input WHERE region IN ('US', 'EU')")

    # Aggregate
    aggregated = filtered.group_by("customer_id").aggregate(
        total_amount=filtered.amount.sum()
    )

    # Write + count
    t3 = time.perf_counter()
    backend = aggregated._find_backend()
    backend.create_view("_dte_json_output", aggregated, overwrite=True)
    (count_in,) = backend.con.execute("SELECT COUNT(*) FROM _load_input").fetchone()
    (rows_written,) = backend.con.execute("SELECT COUNT(*) FROM _dte_json_output").fetchone()
    t4 = time.perf_counter()
    print(f"  [COUNT(*) done: in={count_in:,}  out={rows_written:,}  in {t4-t3:.2f}s]", flush=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_str = str(out_path).replace("'", "''")
    backend.con.execute(f"COPY _dte_json_output TO '{out_str}' (FORMAT JSON, ARRAY true)")
    t5 = time.perf_counter()
    print(f"  [COPY done in {t5-t4:.2f}s]", flush=True)

    elapsed = time.perf_counter() - t0
    rss_after = rss_mb()
    _, peak_traced = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    output_mb = out_path.stat().st_size / 1024 / 1024

    print(f"\n  Input rows:       {count_in:>12,}", flush=True)
    print(f"  Output rows:      {rows_written:>12,}", flush=True)
    print(f"  Elapsed:          {elapsed:>12.2f}s", flush=True)
    print(f"  Throughput:       {count_in/elapsed:>12,.0f} rows/s", flush=True)
    print(f"  RSS before:       {rss_before:>12.1f} MB", flush=True)
    print(f"  RSS after:        {rss_after:>12.1f} MB", flush=True)
    print(f"  Traced peak:      {peak_traced/1024/1024:>12.1f} MB", flush=True)
    print(f"  Output file:      {output_mb:>12.2f} MB", flush=True)

    RUN_MAX_ROWS = 10_000_000
    if count_in > RUN_MAX_ROWS:
        print(f"\n  GUARDRAIL: WOULD FIRE — {count_in:,} > run_max_rows ({RUN_MAX_ROWS:,})")
    else:
        print(f"\n  GUARDRAIL: OK — {count_in:,} <= run_max_rows ({RUN_MAX_ROWS:,})")

    return {"rows_in": count_in, "rows_out": rows_written, "elapsed_s": round(elapsed, 2), "rss_peak_mb": round(rss_after, 1)}


if __name__ == "__main__":
    data_dir = WORKTREE / "data" / "load_test"
    run_test(
        jsonl_path=data_dir / "orders_10m.jsonl",
        out_path=data_dir / "output_10m.json",
        label="10M Row Load Test — DuckDB direct",
    )
