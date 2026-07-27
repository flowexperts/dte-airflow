"""Generate a synthetic JSONL dataset for load testing.

Usage:
    uv run python backend/scripts/gen_load_fixture.py --rows 1000000
    uv run python backend/scripts/gen_load_fixture.py --rows 10000000

Output: ./data/load_test/orders.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from pathlib import Path

REGIONS = ["US", "EU", "APAC", "LATAM", "MEA"]
# Only US and EU will pass the filter step, so we skew toward them
REGION_WEIGHTS = [0.40, 0.30, 0.15, 0.10, 0.05]


def gen_row(i: int) -> dict:
    region = random.choices(REGIONS, weights=REGION_WEIGHTS)[0]
    customer_id = f"cust_{random.randint(1, 5000):05d}"
    amount = round(random.uniform(1.0, 9999.99), 2)
    ts = f"2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}T{random.randint(0,23):02d}:{random.randint(0,59):02d}:00Z"
    return {
        "id": i,
        "customer_id": customer_id,
        "amount": amount,
        "ts": ts,
        "region": region,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate load-test fixture")
    parser.add_argument("--rows", type=int, default=1_000_000, help="Number of rows to generate")
    parser.add_argument(
        "--out",
        default="data/load_test/orders.jsonl",
        help="Output path (relative to repo root)",
    )
    args = parser.parse_args()

    # Resolve output path relative to repo root (two levels up from backend/scripts/)
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent.parent
    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = args.rows
    report_every = max(100_000, rows // 20)

    print(f"Generating {rows:,} rows → {out_path}", flush=True)
    t0 = time.perf_counter()

    with open(out_path, "w") as f:
        for i in range(1, rows + 1):
            f.write(json.dumps(gen_row(i)))
            f.write("\n")
            if i % report_every == 0:
                pct = i / rows * 100
                elapsed = time.perf_counter() - t0
                rate = i / elapsed
                eta = (rows - i) / rate if rate > 0 else 0
                print(
                    f"  {i:>10,} / {rows:,}  ({pct:.0f}%)  "
                    f"{elapsed:.1f}s elapsed  ETA {eta:.0f}s  rate {rate/1000:.0f}k rows/s",
                    flush=True,
                )

    elapsed = time.perf_counter() - t0
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(
        f"Done. {rows:,} rows in {elapsed:.1f}s  ({size_mb:.0f} MB)  {rows/elapsed/1000:.0f}k rows/s",
        flush=True,
    )


if __name__ == "__main__":
    random.seed(42)
    main()
