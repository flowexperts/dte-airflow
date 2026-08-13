"""Direct DuckDB load test — bypasses the API/Postgres layer.

Runs the same pipeline logic (filter + aggregate) directly against the DuckDB
engine so we can measure pure compute + memory performance independent of
the Postgres store or HTTP layer.

Usage:
    uv run python backend/scripts/load_test_direct.py --rows 1000000
    uv run python backend/scripts/load_test_direct.py --rows 10000000
"""
from __future__ import annotations

import argparse
import gc
import os
import resource
import time
import tracemalloc
from pathlib import Path

import ibis

WKDIR = Path(__file__).parent.parent.parent   # worktree root (has data/)


def rss_mb() -> float:
    """Return current RSS in MiB (macOS/Linux)."""
    try:
        # macOS: ru_maxrss in bytes
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux: ru_maxrss in KB; macOS: bytes
        if os.uname().sysname == "Darwin":
            return usage / 1024 / 1024
        return usage / 1024
    except Exception:
        return 0.0


def run(jsonl_path: Path, out_path: Path, rows_hint: int) -> dict:
    gc.collect()
    tracemalloc.start()
    rss_before = rss_mb()
    t0 = time.perf_counter()

    # ── 1. Connect & load source ──────────────────────────────────────────────
    print("  [1] Connecting to DuckDB...", flush=True)
    con = ibis.duckdb.connect()
    native = con.con   # duckdb.DuckDBPyConnection

    # Load via DuckDB native read_json_auto (same path as filesystem loader)
    t_load = time.perf_counter()
    native.execute(f"""
        CREATE OR REPLACE VIEW _load_input AS
        SELECT * FROM read_json_auto('{jsonl_path}', maximum_object_size=10485760)
    """)
    source_table = con.table("_load_input")
    count_pre = native.execute("SELECT COUNT(*) FROM _load_input").fetchone()[0]
    t_load_done = time.perf_counter()
    print(f"  [1] Loaded view in {t_load_done - t_load:.2f}s — {count_pre:,} rows visible", flush=True)

    # ── 2. Filter step (region IN ('US', 'EU')) ───────────────────────────────
    t_filter = time.perf_counter()
    con.create_view("_filter_input", source_table, overwrite=True)
    filtered = con.sql("SELECT * FROM _filter_input WHERE region IN ('US', 'EU')")
    t_filter_done = time.perf_counter()
    print(f"  [2] Filter compiled in {t_filter_done - t_filter:.3f}s (lazy)", flush=True)

    # ── 3. Aggregate step (sum(amount) GROUP BY customer_id) ──────────────────
    t_agg = time.perf_counter()
    aggregated = filtered.group_by("customer_id").aggregate(
        total_amount=filtered.amount.sum()
    )
    t_agg_done = time.perf_counter()
    print(f"  [3] Aggregate compiled in {t_agg_done - t_agg:.3f}s (lazy)", flush=True)

    # ── 4. Write output (DuckDB COPY, streaming) ──────────────────────────────
    t_write = time.perf_counter()
    backend = aggregated._find_backend()
    backend.create_view("_dte_json_output", aggregated, overwrite=True)
    (rows_written,) = backend.con.execute("SELECT COUNT(*) FROM _dte_json_output").fetchone()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_str = str(out_path).replace("'", "''")
    backend.con.execute(
        f"COPY _dte_json_output TO '{out_str}' (FORMAT JSON, ARRAY true)"
    )
    t_write_done = time.perf_counter()
    print(f"  [4] Write done in {t_write_done - t_write:.2f}s — {rows_written:,} rows written", flush=True)

    elapsed = time.perf_counter() - t0
    rss_after = rss_mb()
    _, peak_traced = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    output_mb = out_path.stat().st_size / 1024 / 1024

    return {
        "rows_input": count_pre,
        "rows_written": int(rows_written),
        "elapsed_s": round(elapsed, 2),
        "rss_before_mb": round(rss_before, 1),
        "rss_after_mb": round(rss_after, 1),
        "peak_traced_mb": round(peak_traced / 1024 / 1024, 1),
        "output_mb": round(output_mb, 2),
        "stage_load_s": round(t_load_done - t_load, 3),
        "stage_write_s": round(t_write_done - t_write, 3),
        "throughput_rows_per_s": round(count_pre / elapsed),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1_000_000)
    args = parser.parse_args()

    sizes = [1_000_000, 10_000_000]
    target_size = args.rows

    # Only generate if needed
    for size in sizes:
        if size > target_size:
            break
        jsonl = WKDIR / "data" / "load_test" / "orders.jsonl"
        if not jsonl.exists() or jsonl.stat().st_size < size * 80:  # rough: ~105 bytes/row
            print(f"\nNeed {size:,} rows — generate first with gen_load_fixture.py --rows {size}")
            return

    jsonl_path = WKDIR / "data" / "load_test" / "orders.jsonl"
    out_path = WKDIR / "data" / "load_test" / "output.json"

    if not jsonl_path.exists():
        print(f"ERROR: {jsonl_path} not found. Run gen_load_fixture.py first.")
        return

    file_mb = jsonl_path.stat().st_size / 1024 / 1024
    print(f"\n=== DTE Direct Load Test ===")
    print(f"Input:  {jsonl_path}  ({file_mb:.0f} MB)")
    print(f"Output: {out_path}")
    print(f"Steps:  filter(region IN US,EU)  +  aggregate(sum(amount) by customer_id)")
    print()

    result = run(jsonl_path, out_path, args.rows)

    print()
    print("=== RESULTS ===")
    print(f"  Input rows:          {result['rows_input']:>12,}")
    print(f"  Output rows:         {result['rows_written']:>12,}  (after filter+agg)")
    print(f"  Elapsed:             {result['elapsed_s']:>12.2f}s")
    print(f"  Throughput:          {result['throughput_rows_per_s']:>12,} rows/s")
    print(f"  RSS before:          {result['rss_before_mb']:>12.1f} MB")
    print(f"  RSS after (peak):    {result['rss_after_mb']:>12.1f} MB")
    print(f"  Traced peak:         {result['peak_traced_mb']:>12.1f} MB")
    print(f"  Output file:         {result['output_mb']:>12.2f} MB")
    print(f"  Stage load_view:     {result['stage_load_s']:>12.3f}s")
    print(f"  Stage write/copy:    {result['stage_write_s']:>12.3f}s")

    # Guardrail check — would run_max_rows have fired?
    # Default in _execute_pipeline is 10_000_000 (see dte/api/routes/pipelines.py)
    RUN_MAX_ROWS = 10_000_000
    if result["rows_input"] > RUN_MAX_ROWS:
        print(f"\n  GUARDRAIL: input ({result['rows_input']:,}) > run_max_rows ({RUN_MAX_ROWS:,}) — would have been rejected")
    else:
        print(f"\n  GUARDRAIL: OK — {result['rows_input']:,} rows < run_max_rows ({RUN_MAX_ROWS:,})")


if __name__ == "__main__":
    main()
