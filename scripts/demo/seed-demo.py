"""Seed the demo warehouse's connection, sources, destinations and pipelines.

Everything goes over the HTTP API (same pattern as docs/user/scripts/seed.py)
so the seeded objects are indistinguishable from ones a user clicked together
— which matters, because the recordings edit them on camera.

Idempotent: PUT first, POST on 404. Run it twice; the second run changes
nothing.

Stdlib only (urllib, not httpx) so it runs against a bare `python3` without
the backend venv — verify.sh and the recording scripts both shell out to it.

Prereqs:
    docker compose up -d --build          # incl. the postgres-demo service
    # scripts/demo/seed/01-warehouse.sql has already run via initdb

Usage:
    python3 scripts/demo/seed-demo.py
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("DTE_URL", "http://localhost:8001")
EMAIL = os.environ.get("DTE_EMAIL", "demo@example.com")
PASSWORD = os.environ.get("DTE_PASSWORD", "demopass1234")

# Reached from inside the backend/worker containers, so this is the compose
# service name and the internal port — NOT localhost:5433, which is only the
# host-side mapping.
WAREHOUSE_URL = os.environ.get(
    "DTE_DEMO_WAREHOUSE_URL", "postgresql://demo:demo@postgres-demo:5432/warehouse"
)

CONNECTIONS = [
    {
        "id": "demo_warehouse",
        "name": "Demo warehouse",
        "connection_type": "postgres",
        "credentials": {"url": WAREHOUSE_URL},
    },
]

# One Source per schema. The physical table is chosen per pipeline via
# SourceTableRef{source_id, table, alias} (plan 056), so three sources cover
# all eight tables.
SOURCES = [
    {"id": "demo_crm", "name": "CRM", "source_type": "sql_database",
     "connection_id": "demo_warehouse", "table": "customers", "config": {"schema": "crm"}},
    {"id": "demo_sales", "name": "Order system", "source_type": "sql_database",
     "connection_id": "demo_warehouse", "table": "orders", "config": {"schema": "sales"}},
    {"id": "demo_staging", "name": "Landing zone", "source_type": "sql_database",
     "connection_id": "demo_warehouse", "table": "invoice_lines", "config": {"schema": "staging"}},
    # The invoice corpus: git-tracked PDFs, bind-mounted read-only into both
    # backend and worker at /app/sample_data.
    {"id": "demo_invoices", "name": "Vendor invoices (PDF)", "source_type": "documents",
     "connection_id": "demo_local", "table": "invoices",
     "config": {"bucket_url": "/app/sample_data/eval-demo/invoices", "file_glob": "**/*.pdf"}},
]

# `documents` is filesystem-family, so it needs a local_fs connection rather
# than the warehouse one.
CONNECTIONS.append(
    {"id": "demo_local", "name": "Local files", "connection_type": "local_fs", "credentials": {}}
)

DESTINATIONS = [
    {"id": "demo_order_facts", "name": "analytics.order_facts",
     "connection_id": "demo_warehouse",
     "config": {"type": "postgres", "schema": "analytics", "table": "order_facts",
                "write_disposition": "replace"}},
    {"id": "demo_invoice_lines", "name": "staging.invoice_lines",
     "connection_id": "demo_warehouse",
     "config": {"type": "postgres", "schema": "staging", "table": "invoice_lines",
                "write_disposition": "replace"}},
    {"id": "demo_customer_orders", "name": "analytics.customer_orders",
     "connection_id": "demo_warehouse",
     "config": {"type": "postgres", "schema": "analytics", "table": "customer_orders",
                "write_disposition": "replace"}},
    {"id": "demo_recon", "name": "analytics.invoice_reconciliation",
     "connection_id": "demo_warehouse",
     "config": {"type": "postgres", "schema": "analytics", "table": "invoice_reconciliation",
                "write_disposition": "replace"}},
]

# ─── Pipeline A: the flagship ─────────────────────────────────────────────
#
# Two sources, five table refs, four joins across three different `on`
# shapes. engine "auto" resolves to postgres pushdown because every source
# shares one Connection — which is exactly why the schemas live in one
# database (see the seed SQL's header).

ORDER_FACTS = {
    "id": "demo_order_facts_pipeline",
    "name": "Order facts",
    "sources": [
        {"source_id": "demo_sales", "table": "orders", "alias": "orders"},
        {"source_id": "demo_sales", "table": "order_items", "alias": "items"},
        {"source_id": "demo_sales", "table": "products", "alias": "products"},
        {"source_id": "demo_crm", "table": "customers", "alias": "customers"},
        {"source_id": "demo_crm", "table": "regions", "alias": "regions"},
    ],
    "params": [
        {"name": "min_order_date", "type": "date", "required": True,
         "default": "2024-01-01",
         "description": "Only include orders placed on or after this date."},
    ],
    "output_id": "demo_order_facts",
    "engine": "auto",
    "steps": [
        # 1–4: the join chain. Each writes a new registry key that the next
        # one reads, so the order is load-bearing.
        {"op": "join", "left": "orders", "right": "items",
         "on": "order_id", "how": "inner", "output_id": "oi"},
        {"op": "join", "left": "oi", "right": "products",
         "on": "product_id", "how": "left", "output_id": "oip"},
        {"op": "join", "left": "oip", "right": "customers",
         "on": {"customer_id": "customer_id"}, "how": "inner", "output_id": "oipc"},
        {"op": "join", "left": "oipc", "right": "regions",
         "on": "region_code", "how": "left", "output_id": "facts"},

        {"op": "filter",
         "expr": "\"status\" <> 'cancelled' AND \"ordered_at\" >= '{{params.min_order_date}}'"},

        # Price paid, not catalogue price — that is why products.list_price
        # is named differently.
        {"op": "map", "mode": "expression", "output_field": "line_total",
         "expr": "qty * unit_price"},
        {"op": "map", "mode": "expression", "output_field": "amount_after_discount",
         "expr": "qty * unit_price * (1 - discount_pct / 100.0)"},

        {"op": "case", "output_field": "order_size",
         "branches": [
             {"when": [{"field": "line_total", "op": ">", "value": "1000"}], "then": "large"},
             {"when": [{"field": "line_total", "op": ">", "value": "250"}], "then": "medium"},
         ],
         "otherwise": "small"},

        {"op": "rename", "mappings": {"full_name": "customer_name", "qty": "quantity"}},
        {"op": "sort", "by": ["ordered_at"], "ascending": False},

        # What clicking through Auto-map produces: one select step whose
        # aliases do the renaming. record-core-join.mjs DELETES this step and
        # rebuilds it live on camera — it is seeded so that the 90-second cut
        # and verify.sh have a runnable pipeline without a browser.
        #
        # Seeding it is not optional. dlt's `replace` disposition replaces
        # rows but EVOLVES schema, so triggering this pipeline without a
        # select appends all 28 intermediate columns (`product_id_right`,
        # `discount_pct`, `email`, …) to analytics.order_facts permanently,
        # and no later run removes them. One bare run poisons the Auto-map
        # demo until the warehouse volume is dropped.
        {"op": "select", "fields": [
            {"field": "order_id"},
            {"field": "ordered_at"},
            {"field": "status"},
            {"field": "customer_name"},
            {"field": "region_name"},
            {"field": "quantity"},
            {"field": "tier", "alias": "account_tier"},
            {"field": "category", "alias": "product_category"},
            {"field": "line_total", "alias": "gross_amount"},
            {"field": "amount_after_discount", "alias": "net_amount"},
            {"field": "order_size", "alias": "size_band"},
        ]},
    ],
}

# ─── Pipeline B: PDFs into the warehouse ──────────────────────────────────
#
# engine duckdb: a documents source lands in DuckDB, and ENGINE_WRITE_SUPPORT
# lets duckdb write postgres. This is the legal way across the backend
# boundary that a direct PDF-to-Postgres join could never be.

INVOICE_EXTRACT = {
    "id": "demo_invoice_extract",
    "name": "Invoice extract",
    "sources": [{"source_id": "demo_invoices", "alias": "invoices"}],
    "output_id": "demo_invoice_lines",
    "engine": "duckdb",
    "steps": [
        {"op": "extract", "source_field": "path", "provider": "pdfplumber",
         "granularity": "document", "output_field": "content"},
        {"op": "structure", "input_field": "content", "provider": "claude",
         "on_error": "null",
         "model": {
             "instructions": (
                 "These are vendor freight invoices. Read the totals as plain "
                 "numbers — drop currency symbols and thousands separators."
             ),
             "fields": [
                 {"name": "invoice_number", "type": "string", "required": True,
                  "description": "The invoice identifier, e.g. INV-1001.",
                  "examples": ["INV-1001"]},
                 {"name": "vendor", "type": "string", "required": True,
                  "description": "The company that issued the invoice."},
                 {"name": "invoice_date", "type": "date",
                  "description": "Date on the invoice. Null if absent."},
                 {"name": "total", "type": "float", "required": True,
                  "description": "Invoice total as a number, e.g. 1240.50."},
                 {"name": "freight", "type": "float",
                  "description": "Freight or shipping charge if itemised, else null."},
             ],
         }},
        {"op": "select", "fields": [
            {"field": "invoice_number"}, {"field": "vendor"},
            {"field": "invoice_date"}, {"field": "total"}, {"field": "freight"},
        ]},
    ],
}

# ─── Pipeline C: reconcile what was extracted ─────────────────────────────
#
# Both sources are on demo_warehouse, so one backend, pushdown, no
# MixedBackendError. The corpus ships two PDFs per invoice number and two of
# those pairs disagree — so this lands on exactly 2 rows.

RECONCILIATION = {
    "id": "demo_invoice_recon",
    "name": "Invoice reconciliation",
    "sources": [
        {"source_id": "demo_staging", "table": "invoice_lines", "alias": "extracted"},
        {"source_id": "demo_sales", "table": "vendor_bills", "alias": "bills"},
    ],
    "output_id": "demo_recon",
    "engine": "postgres",
    "steps": [
        {"op": "join", "left": "extracted", "right": "bills",
         "on": {"invoice_number": "invoice_number"}, "how": "inner", "output_id": "recon"},
        {"op": "map", "mode": "expression", "output_field": "variance",
         "expr": "total - expected_total"},
        {"op": "filter", "expr": "abs(\"total\" - \"expected_total\") > 0.01"},
        {"op": "select", "fields": [
            {"field": "invoice_number"}, {"field": "vendor"},
            {"field": "total", "alias": "extracted_total"},
            {"field": "expected_total"}, {"field": "variance"},
        ]},
    ],
}

PIPELINES = [ORDER_FACTS, INVOICE_EXTRACT, RECONCILIATION]


def call(method: str, path: str, body: dict | None = None,
         token: str | None = None) -> tuple[int, dict | str]:
    """One HTTP call. Returns (status, parsed-body-or-text); never raises on
    a 4xx/5xx, because upsert() needs to branch on 404."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def bootstrap_token() -> str:
    """Register the demo user (idempotent) and return a bearer token."""
    status, _ = call("POST", "/api/auth/register",
                     {"email": EMAIL, "password": PASSWORD})
    if status == 201:
        print(f"  ✓ registered {EMAIL}")
    elif status == 409:
        print(f"  · {EMAIL} exists")
    else:
        print(f"  ! register: {status}")
    status, body = call("POST", "/api/auth/login",
                        {"email": EMAIL, "password": PASSWORD})
    if status != 200:
        raise SystemExit(f"login failed: {status} {body}")
    return body["access_token"]


def upsert(coll: str, items: list[dict], token: str) -> int:
    """PUT, falling back to POST on 404. Idempotent by construction."""
    failures = 0
    for item in items:
        status, body = call("PUT", f"/api/{coll}/{item['id']}", item, token)
        if status == 404:
            status, body = call("POST", f"/api/{coll}", item, token)
        if status >= 400:
            print(f"  ! {coll}/{item['id']}: {status} {body}")
            failures += 1
            continue
        print(f"  ✓ {coll}/{item['id']}")
    return failures


def main() -> int:
    print("auth:")
    token = bootstrap_token()

    failures = 0
    for coll, items in (("connections", CONNECTIONS), ("sources", SOURCES),
                        ("destinations", DESTINATIONS), ("pipelines", PIPELINES)):
        print(f"{coll}:")
        failures += upsert(coll, items, token)

    if failures:
        print(f"\n{failures} object(s) failed to seed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
