# Plan 044: Cloud Storage Integration Tests — Sources, Destinations, and Full Pipelines

## Problem Statement

Cloud storage (S3, GCS, Azure Blob) is tested only at the SQL-generation level in `tests/unit/test_loader.py`. Nothing exercises:

- The real DuckDB `httpfs`/`azure` extension path against a live endpoint
- The `parquet_s3` writer landing files on a live S3 bucket
- A full source→transform→destination pipeline that mixes cloud + local

This plan adds three layers of coverage:

1. **Loader-level integration tests** — verify `_load_s3` / `_load_azure` actually read files from local emulators.
2. **Pipeline-level integration tests** — verify pipelines that mix cloud sources and local/cloud destinations (MinIO source → local JSON; local → MinIO parquet; Azurite source → local JSON) end-to-end via the FastAPI app.
3. **Driver script** that spins up MinIO + Azurite, seeds fixtures, runs the tests, tears down.

**GCS**: skipped with a documented reason — DuckDB `TYPE gcs` hardcodes `storage.googleapis.com` with no endpoint override. Not locally emulatable.

**Azure destination**: no writer exists in `dte/engine/writers/`. Azure is source-only for this plan.

---

## Architecture Change

- **`docker/docker-compose.storage-test.yml`**: MinIO + Azurite only. No Postgres — loader tests need none; pipeline tests use FakeStores (existing autouse setup in `tests/conftest.py`).
- **`scripts/test-cloud-storage.sh`**: start → wait for health → seed via Python (s3fs for MinIO, azure-storage-blob for Azurite) → run pytest → teardown.
- **`backend/dte/sources/loader.py`**: extend `_build_azure_secret_sql` to accept a `connection_string` credential field. Azurite requires `CONNECTION_STRING` with `BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;` to redirect away from Azure cloud — the current function only handles `ACCOUNT_NAME+KEY/SAS`.
- **`backend/tests/integration/test_cloud_storage.py`**: two tiers — loader (direct `_load_*` calls) and pipeline (async httpx over `app` + FakeStores, mirroring the scenario suite).

---

## Blockers Addressed (from plan evaluation)

| # | Blocker | Resolution |
|---|---------|-----------|
| 1 | `mc` binary not in `minio/minio` image → docker-based seeding would fail | Seed via `s3fs` in inline Python (already a transitive dep via `dte/engine/writers/parquet_s3.py`). No docker-in-docker. |
| 2 | `az://` URI format unverified — DuckDB may want `azure://` or `abfss://` | Add a **URI-prefix probe** in the test module that tries each variant at import time and caches the winning prefix for all Azure tests. Prints the winning value under `-s`. |
| 3 | `_INSTALLED_EXTS` module-global may skip LOAD across connections | **Non-issue** — verified `_ensure_ext` (loader.py:292–297) calls `LOAD` unconditionally on every invocation; only `INSTALL` is guarded. |
| 4 | `Source(connection_id="x")` may hit FK/compat validators | **Non-issue** — verified `SourceBase` (pipeline.py:409–473) treats `connection_id` as an opaque `str`. Compat check is API-layer only. Pipeline-tier tests create a real Connection first. |
| 5 | Unused Postgres in compose adds ~10s and a failure mode | **Dropped**. |
| 6 | `azure-storage-blob` heavy dep just for seeding | Kept — ~1MB dep, matches Python-first seeding pattern. `mcr.microsoft.com/azure-cli` alternative is a ~1.5GB image. |

---

## Branch / Worktree

```bash
git worktree add worktrees/cloud-storage-int-tests -b feature/cloud-storage-int-tests
```

All edits happen inside this worktree. Fix errors in-place and continue.

---

## Task List

### Task 1 — Extend `_build_azure_secret_sql` for `connection_string`

**File**: `backend/dte/sources/loader.py` (function at line 161)

Add a `connection_string` early-return branch **before** the existing `account_name` logic:

```python
def _build_azure_secret_sql(credentials: dict, secret_name: str) -> str:
    parts: list[str] = ["TYPE azure"]
    # connection_string short-circuits ACCOUNT_NAME logic.
    # Required for Azurite (BlobEndpoint=http://127.0.0.1:10000/...).
    if "connection_string" in credentials:
        parts.append(_secret_kv("CONNECTION_STRING", resolve_secret(credentials["connection_string"])))
        body = ",\n".join(parts)
        return f"CREATE OR REPLACE SECRET {_sql_ident(secret_name)} (\n{body}\n)"
    # ... existing account_name + key/sas logic unchanged ...
```

Loader-tier tests bypass `ConnectionBase._validate_credentials` by calling `_load_azure` directly with a raw credentials dict. Pipeline-tier tests may need a companion validator tweak (see Task 7 conditional).

---

### Task 2 — Unit tests for the `connection_string` branch

**File**: `backend/tests/unit/test_loader.py` (append after line 324, before `test_dispatch_registers_object_storage_types`):

```python
def test_azure_secret_sql_connection_string():
    from dte.sources.loader import _build_azure_secret_sql
    conn_str = (
        "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;"
        "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
        "K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
    )
    sql = _build_azure_secret_sql({"connection_string": conn_str}, secret_name="az_local")
    assert "TYPE azure" in sql
    assert "CONNECTION_STRING" in sql
    assert "ACCOUNT_NAME" not in sql  # must NOT emit ACCOUNT_NAME when connection_string present


def test_azure_secret_sql_connection_string_env_indirection(monkeypatch):
    from dte.sources.loader import _build_azure_secret_sql
    monkeypatch.setenv("AZURITE_CONN", "DefaultEndpointsProtocol=http;AccountName=x;")
    sql = _build_azure_secret_sql(
        {"connection_string": {"env": "AZURITE_CONN"}}, secret_name="az"
    )
    assert "CONNECTION_STRING 'DefaultEndpointsProtocol=http;AccountName=x;'" in sql
```

Existing `test_azure_secret_sql_missing_credentials_raises` still passes — `{}` still hits the `raise ValueError` (neither `connection_string` nor `azure_storage_account_name`).

Verify: `cd backend && uv run pytest tests/unit/test_loader.py -v -k azure`

---

### Task 3 — `docker/docker-compose.storage-test.yml`

**File**: `docker/docker-compose.storage-test.yml` (create `docker/` at repo root)

```yaml
services:
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"
      - "9001:9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 3s
      timeout: 5s
      retries: 10
      start_period: 5s

  azurite:
    image: mcr.microsoft.com/azure-storage/azurite:latest
    command: azurite-blob --blobHost 0.0.0.0 --blobPort 10000 --skipApiVersionCheck
    ports:
      - "10000:10000"
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:10000/devstoreaccount1"]
      interval: 3s
      timeout: 5s
      retries: 10
      start_period: 3s
```

`--skipApiVersionCheck` — recent DuckDB azure extensions send API versions Azurite doesn't recognise by default; this makes Azurite lenient.

---

### Task 4 — `scripts/test-cloud-storage.sh`

**File**: `scripts/test-cloud-storage.sh` (then `chmod +x`)

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker/docker-compose.storage-test.yml"
BACKEND="$PROJECT_ROOT/backend"

export MINIO_ENDPOINT="http://localhost:9000"
export AZURITE_ENDPOINT="http://localhost:10000"
export AZURITE_CONN="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"

cleanup() {
  echo "==> Tearing down..."
  docker compose -f "$COMPOSE_FILE" down -v 2>/dev/null || true
}
trap cleanup EXIT

echo "==> Starting MinIO + Azurite..."
docker compose -f "$COMPOSE_FILE" up -d

echo "==> Waiting for MinIO..."
until curl -sf "$MINIO_ENDPOINT/minio/health/live" > /dev/null 2>&1; do sleep 1; done

echo "==> Waiting for Azurite..."
until curl -sf "$AZURITE_ENDPOINT/devstoreaccount1" > /dev/null 2>&1; do sleep 1; done

cd "$BACKEND"

echo "==> Seeding MinIO bucket 'dte-test' via s3fs..."
uv run python - << 'PYEOF'
import os, json, pathlib, io
import s3fs
fs = s3fs.S3FileSystem(
    key="minioadmin", secret="minioadmin",
    client_kwargs={"endpoint_url": os.environ["MINIO_ENDPOINT"]},
    use_ssl=False,
)
try:
    fs.mkdirs("dte-test", exist_ok=True)
except Exception:
    pass
src = pathlib.Path("tests/scenarios/fixtures/orders.json")
with fs.open("dte-test/orders.json", "wb") as f:
    f.write(src.read_bytes())
try:
    import pyarrow as pa, pyarrow.parquet as pq
    data = json.loads(src.read_text())
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(data), buf)
    with fs.open("dte-test/orders.parquet", "wb") as f:
        f.write(buf.getvalue())
    print("seeded: orders.json + orders.parquet")
except ImportError:
    print("seeded: orders.json (pyarrow missing — skipped parquet)")
PYEOF

echo "==> Seeding Azurite container 'dte-test' via azure-storage-blob..."
uv run python - << PYEOF
import os, pathlib
from azure.storage.blob import BlobServiceClient
client = BlobServiceClient.from_connection_string(os.environ["AZURITE_CONN"])
try:
    client.create_container("dte-test")
except Exception:
    pass
data = pathlib.Path("tests/scenarios/fixtures/orders.json").read_bytes()
client.get_blob_client("dte-test", "orders.json").upload_blob(data, overwrite=True)
print("seeded: az://dte-test/orders.json")
PYEOF

echo "==> Running integration tests..."
uv run pytest tests/integration/test_cloud_storage.py -m integration -v -s

echo "==> Done."
```

`-s` surfaces the URI-probe output so any failure names the prefix that was tried.

---

### Task 5 — Add `azure-storage-blob` to dev deps

**File**: `backend/pyproject.toml`

In `dev` extras add:
```toml
"azure-storage-blob>=12.0,<13.0",
```

Update the `integration` marker description:
```toml
"integration: tests that require live external services (Postgres, MinIO, Azurite)",
```

Then in the worktree: `cd backend && uv sync --extra dev`

---

### Task 6 — `backend/tests/integration/test_cloud_storage.py`

Two tiers combined in one file. **Loader tier** exercises the raw `_load_*` functions. **Pipeline tier** goes through the FastAPI app with FakeStores (already autouse in `tests/conftest.py:91–144`) to prove sources connect to different destinations.

Fixtures reused: `backend/tests/scenarios/fixtures/orders.json` — 20 rows, fields `order_id, customer_id, product_id, amount, status, ordered_at`.

```python
"""Integration tests for cloud storage.

Loader tier:   _load_s3 / _load_azure against MinIO / Azurite (raw calls).
Pipeline tier: full source→transform→destination via FastAPI (in-process, FakeStores).

Env:
  MINIO_ENDPOINT=http://localhost:9000
  AZURITE_ENDPOINT=http://localhost:10000

Run: bash scripts/test-cloud-storage.sh
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from dte.api.main import app
from dte.engine.backend_registry import BackendRegistry
from dte.models.pipeline import Source
from dte.sources.loader import _load_azure, _load_s3

pytestmark = pytest.mark.integration

_MINIO = os.getenv("MINIO_ENDPOINT")
_AZURITE = os.getenv("AZURITE_ENDPOINT")

_AZURITE_CONN = (
    "DefaultEndpointsProtocol=http;"
    "AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
    "K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
)

# ─── URI-prefix probe (blocker #2) ────────────────────────────────────────
# DuckDB's azure extension has used both `az://` and `azure://` across versions.
# Probe once at import time; cache the winner for all Azure tests.
def _probe_azure_uri_prefix() -> str:
    if not _AZURITE:
        return "az://"
    reg = BackendRegistry()
    for prefix in ("az://", "azure://", "abfss://"):
        source = Source(
            id="probe", connection_id="x", source_type="azure",
            config={"bucket_url": f"{prefix}dte-test", "file_glob": "orders.json"},
            table=f"probe_{prefix.replace(':','').replace('/','')}",
        )
        try:
            _load_azure(source, reg, connection=None,
                        credentials={"connection_string": _AZURITE_CONN}).execute()
            return prefix
        except Exception:
            continue
    raise RuntimeError("no working Azure URI prefix (tried az://, azure://, abfss://)")


_AZURE_PREFIX = _probe_azure_uri_prefix() if _AZURITE else "az://"


# ─── Loader tier: S3 / MinIO ──────────────────────────────────────────────

@pytest.fixture
def registry():
    return BackendRegistry()


@pytest.mark.skipif(not _MINIO, reason="requires MINIO_ENDPOINT")
class TestS3Loader:
    def _creds(self):
        return {
            "aws_access_key_id": "minioadmin",
            "aws_secret_access_key": "minioadmin",
            "endpoint_url": _MINIO,
        }

    def test_reads_json_file(self, registry):
        source = Source(
            id="t-s3-json", connection_id="x", source_type="s3",
            config={"bucket_url": "s3://dte-test", "file_glob": "orders.json"},
            table="s3_orders",
        )
        rows = _load_s3(source, registry, connection=None, credentials=self._creds()).execute()
        assert len(rows) == 20
        assert {"order_id", "customer_id", "amount", "status"}.issubset(set(rows.columns))

    def test_reads_parquet_file(self, registry):
        pytest.importorskip("pyarrow")
        source = Source(
            id="t-s3-parquet", connection_id="x", source_type="s3",
            config={"bucket_url": "s3://dte-test", "file_glob": "orders.parquet"},
            table="s3_orders_parquet",
        )
        rows = _load_s3(source, registry, connection=None, credentials=self._creds()).execute()
        assert len(rows) == 20
        assert "order_id" in rows.columns

    def test_filter_expression(self, registry):
        source = Source(
            id="t-s3-filter", connection_id="x", source_type="s3",
            config={"bucket_url": "s3://dte-test", "file_glob": "orders.json"},
            table="s3_orders_filter",
        )
        table = _load_s3(source, registry, connection=None, credentials=self._creds())
        paid = table.filter(table.status == "paid").execute()
        assert len(paid) > 0
        assert all(s == "paid" for s in paid["status"].tolist())


# ─── Loader tier: Azure / Azurite ─────────────────────────────────────────

@pytest.mark.skipif(not _AZURITE, reason="requires AZURITE_ENDPOINT")
class TestAzureLoader:
    def test_reads_json_file(self, registry, capsys):
        with capsys.disabled():
            print(f"[Azure] using URI prefix: {_AZURE_PREFIX}")
        source = Source(
            id="t-az-json", connection_id="x", source_type="azure",
            config={"bucket_url": f"{_AZURE_PREFIX}dte-test", "file_glob": "orders.json"},
            table="az_orders",
        )
        rows = _load_azure(source, registry, connection=None,
                          credentials={"connection_string": _AZURITE_CONN}).execute()
        assert len(rows) == 20
        assert {"order_id", "amount"}.issubset(set(rows.columns))

    def test_aggregate(self, registry):
        source = Source(
            id="t-az-agg", connection_id="x", source_type="azure",
            config={"bucket_url": f"{_AZURE_PREFIX}dte-test", "file_glob": "orders.json"},
            table="az_orders_agg",
        )
        table = _load_azure(source, registry, connection=None,
                           credentials={"connection_string": _AZURITE_CONN})
        total = table.agg(table.amount.sum().name("total")).execute()
        assert total["total"].iloc[0] > 0


# ─── GCS (skipped) ────────────────────────────────────────────────────────

@pytest.mark.skip(
    reason="DuckDB TYPE gcs hardcodes storage.googleapis.com — no ENDPOINT override."
)
def test_gcs_not_locally_testable():
    pass


# ─── Pipeline tier: full source→destination flows ─────────────────────────

@pytest_asyncio.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _create(client, path, body):
    r = await client.post(path, json=body)
    assert r.status_code in (200, 201), f"{path} → {r.status_code}: {r.text}"
    return r.json()


async def _trigger_and_wait(client, pipeline_id: str, timeout: float = 30.0) -> dict:
    r = await client.post(f"/api/pipelines/{pipeline_id}/trigger")
    assert r.status_code in (200, 201), r.text
    run_id = r.json()["run_id"]
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        r = await client.get(f"/api/runs/{run_id}")
        run = r.json()
        if run["status"] in ("completed", "failed"):
            return run
        await asyncio.sleep(0.3)
    raise TimeoutError(f"run {run_id} did not finish in {timeout}s")


@pytest.mark.skipif(not _MINIO, reason="requires MINIO_ENDPOINT")
async def test_pipeline_s3_source_to_local_json(client, tmp_path):
    """MinIO S3 source → filter step → local json_file destination."""
    out = tmp_path / "s3_to_local.json"

    await _create(client, "/api/connections", {
        "id": "conn-s3-minio", "connection_type": "s3",
        "credentials": {
            "aws_access_key_id": "minioadmin",
            "aws_secret_access_key": "minioadmin",
            "endpoint_url": _MINIO,
        },
    })
    await _create(client, "/api/sources", {
        "id": "src-s3", "connection_id": "conn-s3-minio",
        "source_type": "s3",
        "config": {"bucket_url": "s3://dte-test", "file_glob": "orders.json"},
        "table": "orders",
    })
    await _create(client, "/api/destinations", {
        "id": "dst-local-json", "connection_id": "local_fs",
        "config": {"type": "json_file", "path": str(out)},
    })
    await _create(client, "/api/pipelines", {
        "id": "pl-s3-local", "name": "s3 to local",
        "sources": ["src-s3"],
        "steps": [{"op": "filter", "expr": "status = 'paid'"}],
        "output_id": "dst-local-json",
    })

    run = await _trigger_and_wait(client, "pl-s3-local")
    assert run["status"] == "completed", run.get("error")
    assert out.exists()
    rows = json.loads(out.read_text())
    assert len(rows) > 0
    assert all(r["status"] == "paid" for r in rows)


@pytest.mark.skipif(not _MINIO, reason="requires MINIO_ENDPOINT")
async def test_pipeline_local_source_to_s3_parquet(client, tmp_path):
    """Local filesystem source → filter → parquet_s3 destination (writes to MinIO)."""
    pytest.importorskip("pyarrow")
    src_file = tmp_path / "input.json"
    src_file.write_text(pathlib.Path("tests/scenarios/fixtures/orders.json").read_text())

    await _create(client, "/api/connections", {
        "id": "conn-s3-dst", "connection_type": "s3",
        "credentials": {
            "aws_access_key_id": "minioadmin",
            "aws_secret_access_key": "minioadmin",
            "endpoint_url": _MINIO,
        },
    })
    await _create(client, "/api/sources", {
        "id": "src-local", "connection_id": "local_fs",
        "source_type": "filesystem",
        "config": {"bucket_url": str(tmp_path), "file_glob": "input.json"},
        "table": "orders_local",
    })
    await _create(client, "/api/destinations", {
        "id": "dst-s3-parquet", "connection_id": "conn-s3-dst",
        "config": {"type": "parquet_s3", "bucket_url": "s3://dte-test/pipeline_out.parquet"},
    })
    await _create(client, "/api/pipelines", {
        "id": "pl-local-s3", "name": "local to s3",
        "sources": ["src-local"],
        "steps": [{"op": "filter", "expr": "amount > 10"}],
        "output_id": "dst-s3-parquet",
    })

    run = await _trigger_and_wait(client, "pl-local-s3")
    assert run["status"] == "completed", run.get("error")
    assert run["rows_written"] > 0

    # Verify the parquet landed in MinIO
    import s3fs
    fs = s3fs.S3FileSystem(
        key="minioadmin", secret="minioadmin",
        client_kwargs={"endpoint_url": _MINIO}, use_ssl=False,
    )
    assert fs.exists("dte-test/pipeline_out.parquet")


@pytest.mark.skipif(not _AZURITE, reason="requires AZURITE_ENDPOINT")
async def test_pipeline_azure_source_to_local_json(client, tmp_path):
    """Azurite Azure source → rename step → local json_file destination."""
    out = tmp_path / "az_to_local.json"

    await _create(client, "/api/connections", {
        "id": "conn-az", "connection_type": "azure",
        # NOTE: ConnectionBase._validate_credentials may reject connection_string
        # (dlt's AzureCredentials doesn't declare that field). If a 422 fires,
        # pad the dict with `azure_storage_account_name: "devstoreaccount1"`;
        # loader still picks connection_string first (Task 1 branch order).
        "credentials": {"connection_string": _AZURITE_CONN},
    })
    await _create(client, "/api/sources", {
        "id": "src-az", "connection_id": "conn-az",
        "source_type": "azure",
        "config": {"bucket_url": f"{_AZURE_PREFIX}dte-test", "file_glob": "orders.json"},
        "table": "orders_az",
    })
    await _create(client, "/api/destinations", {
        "id": "dst-local-az", "connection_id": "local_fs",
        "config": {"type": "json_file", "path": str(out)},
    })
    await _create(client, "/api/pipelines", {
        "id": "pl-az-local", "name": "az to local",
        "sources": ["src-az"],
        "steps": [{"op": "rename", "renames": {"order_id": "id"}}],
        "output_id": "dst-local-az",
    })

    run = await _trigger_and_wait(client, "pl-az-local")
    assert run["status"] == "completed", run.get("error")
    rows = json.loads(out.read_text())
    assert len(rows) == 20
    assert "id" in rows[0]
    assert "order_id" not in rows[0]
```

**Key design notes**:

- Uses `AsyncClient(ASGITransport(app=app))` — same pattern as `tests/scenarios/conftest.py:47–56`.
- No new fixture infra: `tests/conftest.py` autouse block already installs FakeStores + pre-seeded `local_fs` connection for every test under `tests/` (including `tests/integration/`).
- Pipeline steps use `filter` and `rename` — both exist per CLAUDE.md step dispatch.
- The Azure connection creation carries an inline comment for the fallback if `_validate_credentials` rejects `connection_string` — verify empirically on first run.

---

### Task 7 (conditional) — `AzureCredentials` model accepts `connection_string`

Only if Task 6's pipeline-tier Azure test hits a 422 on `POST /api/connections`.

**File**: `backend/dte/models/pipeline.py` — `_DLT_CRED_CLASS` mapping.

Two options:
- **Option A (minimal)**: pad the test's credential dict with `azure_storage_account_name: "devstoreaccount1"` — satisfies the existing dlt-based validator, loader branch order still picks `connection_string` first. Test-only change, zero model impact.
- **Option B (proper)**: extend the Azure dlt spec whitelist so `connection_string` is a recognised field. Cleaner but touches production code paths. Defer unless someone else needs it.

Default: Option A. Note in the test comment.

---

## Verification

```bash
# Unit tests (no docker):
cd backend && uv run pytest tests/unit/test_loader.py -v -k azure

# Confirm cloud tests excluded from default run:
cd backend && uv run pytest --collect-only 2>&1 | grep test_cloud_storage  # empty

# Confirm tests collected when targeted:
cd backend && uv run pytest tests/integration/test_cloud_storage.py --collect-only

# Full end-to-end (needs Docker):
bash scripts/test-cloud-storage.sh
```

**Expected on green**:
- Loader tests (5): S3 json/parquet/filter + Azure json/aggregate all pass.
- Pipeline tests (3): S3→local json, local→S3 parquet, Azure→local json all reach `status=completed` with expected row shape/count.
- GCS test: `SKIPPED (DuckDB TYPE gcs hardcodes storage.googleapis.com...)`.

---

## Files Changed / Created

| Action | Path |
|--------|------|
| modify | `backend/dte/sources/loader.py` (add `connection_string` branch in `_build_azure_secret_sql`) |
| modify | `backend/tests/unit/test_loader.py` (append 2 unit tests) |
| modify | `backend/pyproject.toml` (add `azure-storage-blob` dev dep, update marker description) |
| create | `docker/docker-compose.storage-test.yml` |
| create | `scripts/test-cloud-storage.sh` (chmod +x) |
| create | `backend/tests/integration/test_cloud_storage.py` |
| modify (conditional) | `backend/dte/models/pipeline.py` — only if Azure pipeline test hits 422 |

---

## Remaining Empirical Unknowns

Verify on first run inside the worktree; fix in place:

1. **Azure URI prefix** — `_probe_azure_uri_prefix` picks the working prefix at import time. If all three fail (`az://`, `azure://`, `abfss://`), likely a DuckDB azure-extension / Azurite API-version mismatch. `--skipApiVersionCheck` on Azurite mitigates most cases.

2. **Azure connection_string via API** — see Task 7. Default fallback baked into test comment.

3. **`parquet_s3` writer with MinIO** — `dte/engine/writers/parquet_s3.py:10–20` already maps `endpoint_url` for fsspec. If the write fails against MinIO, add `use_ssl=False` to `_fsspec_storage_options` when the endpoint is `http://…`.
