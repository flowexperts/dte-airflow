"""Generate the eval-demo invoice PDFs used by `demo_invoices` and friends.

These used to be hand-created files living only at
`/tmp/dte-samples/eval-demo/invoices` on whatever host happened to run
compose. `/tmp` gets swept (macOS, CI, a reboot) and the corpus vanished
with no way to reproduce it — the `documents` source found zero files, and
the labels in `eval_examples` (keyed by `sha256(document bytes)`) pointed at
nothing.

This script is the fix: the corpus is defined here as plain text, built with
the same `pdf_builder.build_pdf` the test suite uses (one text-showing
operator per line — pdfplumber's word segmentation depends on that, see its
docstring), and written into `backend/sample_data/eval-demo/invoices/`,
which is committed to git and bind-mounted into the containers. Run this
again any time the directory needs to be rebuilt; the output is
deterministic, so a rerun with no data changes reproduces byte-identical
files.

Usage:
    cd backend
    uv run python scripts/generate_eval_demo_invoices.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests" / "fixtures"))
from pdf_builder import build_pdf  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "sample_data" / "eval-demo" / "invoices"

# (filename, page lines). Vendor name varies per invoice number on purpose —
# the eval set exercises extraction across differently-worded documents for
# the same field set, not ten copies of one layout.
INVOICES: list[tuple[str, list[str]]] = [
    ("acme-inv1001-freight.pdf", [
        "ACME Freight", "Invoice INV-1001", "Total: $1,240.50",
    ]),
    ("acme-inv1001-dated.pdf", [
        "ACME Freight", "Invoice INV-1001", "Date: 2026-03-01", "Total: $1,240.50",
    ]),
    ("acme-inv1002.pdf", [
        "ACME Freight", "Invoice INV-1002", "Total: $87.00",
    ]),
    ("northwind-inv1002.pdf", [
        "Northwind Logistics", "Invoice INV-1002", "Date: 2026-03-04", "Total: $87.00",
    ]),
    ("globex-inv1003-shipping.pdf", [
        "Globex Shipping", "Invoice INV-1003", "Date: 2026-03-11", "Total: $9,999.99",
    ]),
    ("globex-inv1003-corp.pdf", [
        "Globex Corp", "Invoice INV-1003", "Total: $9,999.99",
    ]),
    ("initech-inv1004.pdf", [
        "Initech LLC", "Invoice INV-1004", "Total: $340.00",
    ]),
    ("initech-inv1004-cartage.pdf", [
        "Initech Cartage", "Invoice INV-1004", "Date: 2026-03-18", "Total: $412.75",
    ]),
    ("umbrella-inv1005-transport.pdf", [
        "Umbrella Transport", "Invoice INV-1005", "Date: 2026-03-22", "Total: $2,050.00",
    ]),
    ("umbrella-inv1005-co.pdf", [
        "Umbrella Co", "Invoice INV-1005", "Total: $12,000.00",
    ]),
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, lines in INVOICES:
        pdf_bytes = build_pdf(["\n".join(lines)])
        path = OUT_DIR / filename
        path.write_bytes(pdf_bytes)
        print(f"wrote {path} ({len(pdf_bytes)} bytes)")


if __name__ == "__main__":
    main()
