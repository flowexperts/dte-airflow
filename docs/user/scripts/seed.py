"""Seed deterministic demo data used by docs/user/scripts/capture.ts.

Reuses the scenario DSL in backend/tests/scenarios/helpers.py so we don't
maintain a parallel seeder.

Usage:
    # stack must be running
    cd backend && uv run python ../docs/user/scripts/seed.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx

BASE = os.environ.get("DTE_URL", "http://localhost:8001")
# Backend mounts /tmp/dte-samples from the host — see docker-compose.yml.
# Container path stays /tmp/dte-samples; write here on the host.
DATA = Path(os.environ.get("DTE_DATA_DIR", "/tmp/dte-samples")).resolve()
EMAIL = os.environ.get("DTE_EMAIL", "demo@example.com")
PASSWORD = os.environ.get("DTE_PASSWORD", "demopass1234")

DEMO_ORDERS = [
    {"id": 1, "customer": "Ada",  "status": "paid",      "amount": 42.50},
    {"id": 2, "customer": "Bo",   "status": "cancelled", "amount": 12.00},
    {"id": 3, "customer": "Cass", "status": "paid",      "amount": 99.90},
]

CONNECTIONS = [
    {"id": "docs_demo_local",    "connection_type": "local_fs", "credentials": {}},
]

SOURCES = [
    {
        "id": "docs_demo_orders",
        "source_type": "filesystem",
        "connection_id": "docs_demo_local",
        "table": "docs_demo_orders",
        "config": {"bucket_url": "/tmp/dte-samples/", "file_glob": "docs_demo_orders.json"},
    },
]

DESTINATIONS = [
    {
        "id": "docs_demo_orders_paid",
        "connection_id": "docs_demo_local",
        "config": {"type": "json_file", "path": "/tmp/dte-samples/docs_demo_orders_paid.json"},
    },
]

PIPELINES = [
    {
        "id": "orders_paid",
        "name": "Paid orders",
        "sources": ["docs_demo_orders"],
        "output_id": "docs_demo_orders_paid",
        "steps": [
            {"op": "filter", "expr": "\"status\" = 'paid'"},
            {"op": "select", "fields": [{"field": "id"}, {"field": "customer"}, {"field": "amount"}]},
        ],
    },
]


async def bootstrap_token(client: httpx.AsyncClient) -> str:
    """Register the demo user (idempotent) and return a bearer token."""
    r = await client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code == 201:
        print(f"  ✓ registered {EMAIL}")
    elif r.status_code == 409:
        print(f"  · {EMAIL} exists")
    else:
        print(f"  ! register: {r.status_code} {r.text}")
    r = await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return r.json()["access_token"]


async def upsert(client: httpx.AsyncClient, coll: str, items: list[dict]) -> None:
    for item in items:
        r = await client.put(f"/api/{coll}/{item['id']}", json=item)
        if r.status_code == 404:
            r = await client.post(f"/api/{coll}", json=item)
        if r.status_code >= 400:
            print(f"  ! {coll}/{item['id']}: {r.status_code} {r.text}")
            continue
        print(f"  ✓ {coll}/{item['id']}")


async def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "docs_demo_orders.json").write_text(json.dumps(DEMO_ORDERS, indent=2))
    print(f"wrote {DATA / 'docs_demo_orders.json'}")

    async with httpx.AsyncClient(base_url=BASE, timeout=15.0) as client:
        print("auth:")
        token = await bootstrap_token(client)
        client.headers["Authorization"] = f"Bearer {token}"

        print("connections:")
        await upsert(client, "connections", CONNECTIONS)
        print("sources:")
        await upsert(client, "sources", SOURCES)
        print("destinations:")
        await upsert(client, "destinations", DESTINATIONS)
        print("pipelines:")
        await upsert(client, "pipelines", PIPELINES)


if __name__ == "__main__":
    asyncio.run(main())
