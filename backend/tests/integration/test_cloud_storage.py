"""Integration tests for cloud storage.

Loader tier:  _load_s3 / _load_azure against MinIO / Azurite.
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
from dte.sources.loader import _load_azure, _load_gcs, _load_s3

pytestmark = pytest.mark.integration

_MINIO = os.getenv("MINIO_ENDPOINT")
_AZURITE = os.getenv("AZURITE_ENDPOINT")
_FAKE_GCS = os.getenv("FAKE_GCS_ENDPOINT")

_AZURITE_CONN = (
    "DefaultEndpointsProtocol=http;"
    "AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
    "K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
)


# ─── URI-prefix probe ─────────────────────────────────────────────────────
# DuckDB azure extension has used both `az://` and `azure://` across versions.
# Probe once at import time; cache the winner for all Azure tests.

def _probe_azure_uri_prefix() -> str:
    if not _AZURITE:
        return "az://"  # unused — tests will skip
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
            print(f"[Azure probe] winning prefix: {prefix}")
            return prefix
        except Exception as exc:
            print(f"[Azure probe] {prefix} failed: {exc}")
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


# ─── Loader tier: GCS / fake-gcs-server ──────────────────────────────────

@pytest.mark.skipif(not _FAKE_GCS, reason="requires FAKE_GCS_ENDPOINT")
class TestGCSLoader:
    def _creds(self):
        return {
            "hmac_key_id": "fake-key",
            "hmac_secret": "fake-secret",
            "endpoint_url": _FAKE_GCS,
        }

    def test_reads_json_file(self, registry):
        source = Source(
            id="t-gcs-json", connection_id="x", source_type="gcs",
            config={"bucket_url": "gcs://dte-test", "file_glob": "orders.json"},
            table="gcs_orders",
        )
        rows = _load_gcs(source, registry, connection=None, credentials=self._creds()).execute()
        assert len(rows) == 20
        assert {"order_id", "customer_id", "amount", "status"}.issubset(set(rows.columns))

    def test_filter_expression(self, registry):
        source = Source(
            id="t-gcs-filter", connection_id="x", source_type="gcs",
            config={"bucket_url": "gcs://dte-test", "file_glob": "orders.json"},
            table="gcs_orders_filter",
        )
        table = _load_gcs(source, registry, connection=None, credentials=self._creds())
        paid = table.filter(table.status == "paid").execute()
        assert len(paid) > 0
        assert all(s == "paid" for s in paid["status"].tolist())


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
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
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
    fixtures_dir = pathlib.Path(__file__).parent.parent / "scenarios" / "fixtures"
    src_file = tmp_path / "input.json"
    src_file.write_text((fixtures_dir / "orders.json").read_text())

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
        "steps": [{"op": "rename", "mappings": {"order_id": "id"}}],
        "output_id": "dst-local-az",
    })

    run = await _trigger_and_wait(client, "pl-az-local")
    assert run["status"] == "completed", run.get("error")
    rows = json.loads(out.read_text())
    assert len(rows) == 20
    assert "id" in rows[0]
    assert "order_id" not in rows[0]


@pytest.mark.skipif(not _FAKE_GCS, reason="requires FAKE_GCS_ENDPOINT")
async def test_pipeline_gcs_source_to_local_json(client, tmp_path):
    """fake-gcs-server GCS source → sort step → local json_file destination."""
    out = tmp_path / "gcs_to_local.json"

    await _create(client, "/api/connections", {
        "id": "conn-gcs", "connection_type": "gcs",
        "credentials": {
            "hmac_key_id": "fake-key",
            "hmac_secret": "fake-secret",
            "endpoint_url": _FAKE_GCS,
        },
    })
    await _create(client, "/api/sources", {
        "id": "src-gcs", "connection_id": "conn-gcs",
        "source_type": "gcs",
        "config": {"bucket_url": "gcs://dte-test", "file_glob": "orders.json"},
        "table": "orders_gcs",
    })
    await _create(client, "/api/destinations", {
        "id": "dst-local-gcs", "connection_id": "local_fs",
        "config": {"type": "json_file", "path": str(out)},
    })
    await _create(client, "/api/pipelines", {
        "id": "pl-gcs-local", "name": "gcs to local",
        "sources": ["src-gcs"],
        "steps": [{"op": "sort", "by": ["amount"], "ascending": False}],
        "output_id": "dst-local-gcs",
    })

    run = await _trigger_and_wait(client, "pl-gcs-local")
    assert run["status"] == "completed", run.get("error")
    rows = json.loads(out.read_text())
    assert len(rows) == 20
    amounts = [r["amount"] for r in rows]
    assert amounts == sorted(amounts, reverse=True)
