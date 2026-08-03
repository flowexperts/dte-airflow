#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker/docker-compose.storage-test.yml"
BACKEND="$PROJECT_ROOT/backend"

export MINIO_ENDPOINT="http://localhost:9000"
export AZURITE_ENDPOINT="http://localhost:10000"
export AZURITE_CONN="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
export FAKE_GCS_ENDPOINT="http://localhost:4443"

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
until curl -s --max-time 2 "$AZURITE_ENDPOINT/" > /dev/null 2>&1; do sleep 1; done

echo "==> Waiting for fake-gcs-server..."
until curl -s --max-time 2 "$FAKE_GCS_ENDPOINT/storage/v1/b" > /dev/null 2>&1; do sleep 1; done

cd "$BACKEND"

echo "==> Seeding MinIO bucket 'dte-test' via s3fs..."
uv run python - << 'PYEOF'
import os, json, pathlib
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
    import pyarrow as pa, pyarrow.parquet as pq, io
    data = json.loads(src.read_text())
    buf = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(data), buf)
    with fs.open("dte-test/orders.parquet", "wb") as f:
        f.write(buf.getvalue())
    print("seeded: orders.json + orders.parquet")
except ImportError:
    print("seeded: orders.json (pyarrow missing — skipped parquet)")
PYEOF

echo "==> Seeding fake-gcs-server bucket 'dte-test' via GCS JSON API..."
uv run python - << 'PYEOF'
import os, pathlib
import httpx

base = os.environ["FAKE_GCS_ENDPOINT"]
# Create bucket
r = httpx.post(f"{base}/storage/v1/b?project=test", json={"name": "dte-test"})
if r.status_code not in (200, 409):
    raise RuntimeError(f"bucket create failed: {r.status_code} {r.text}")
# Upload orders.json
data = pathlib.Path("tests/scenarios/fixtures/orders.json").read_bytes()
r = httpx.post(
    f"{base}/upload/storage/v1/b/dte-test/o?uploadType=media&name=orders.json",
    content=data,
    headers={"Content-Type": "application/json"},
)
if r.status_code not in (200, 201):
    raise RuntimeError(f"upload failed: {r.status_code} {r.text}")
print("seeded: gcs://dte-test/orders.json")
PYEOF

echo "==> Seeding Azurite container 'dte-test' via azure-storage-blob..."
uv run python - << PYEOF
import os, pathlib
from azure.storage.blob import BlobServiceClient
client = BlobServiceClient.from_connection_string(os.environ["AZURITE_CONN"])
try:
    client.create_container("dte-test")
except Exception:
    pass  # already exists
data = pathlib.Path("tests/scenarios/fixtures/orders.json").read_bytes()
client.get_blob_client("dte-test", "orders.json").upload_blob(data, overwrite=True)
print("seeded: az://dte-test/orders.json")
PYEOF

echo "==> Running integration tests..."
uv run pytest tests/integration/test_cloud_storage.py -m integration -v -s

echo "==> Done."
