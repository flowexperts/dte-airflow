#!/usr/bin/env bash
#
# Local S3 / GCS / Azure emulators for cloud-storage work.
#
#   ./scripts/test-cloud-storage.sh          # start, seed, run tests, tear down
#   ./scripts/test-cloud-storage.sh test     # same as above (explicit)
#   ./scripts/test-cloud-storage.sh start    # start + seed, LEAVE RUNNING
#   ./scripts/test-cloud-storage.sh stop     # tear down
#
# `start` is for driving the emulators by hand (pipelines against the API,
# poking around the MinIO console); it skips pytest and the teardown trap so
# the containers survive after the script exits.
set -euo pipefail

MODE="${1:-test}"
case "$MODE" in
  test|start|stop) ;;
  *) echo "usage: $0 [test|start|stop]" >&2; exit 2 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/docker/docker-compose.storage-test.yml"
BACKEND="$PROJECT_ROOT/backend"

export MINIO_ENDPOINT="http://localhost:9000"
export AZURITE_ENDPOINT="http://localhost:10000"
export AZURITE_CONN="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
# Override both to this machine's LAN IP to make the emulator usable from
# containers as well as the host — see docker/docker-compose.storage-test.yml.
export FAKE_GCS_PUBLIC_HOST="${FAKE_GCS_PUBLIC_HOST:-localhost}"
export FAKE_GCS_ENDPOINT="${FAKE_GCS_ENDPOINT:-http://${FAKE_GCS_PUBLIC_HOST}:4443}"

cleanup() {
  echo "==> Tearing down..."
  docker compose -f "$COMPOSE_FILE" down -v 2>/dev/null || true
}

if [[ "$MODE" == "stop" ]]; then
  cleanup
  exit 0
fi

# Only the self-contained test run tears down on exit; `start` deliberately
# leaves the containers up for manual use.
if [[ "$MODE" == "test" ]]; then
  trap cleanup EXIT
fi

echo "==> Starting MinIO + Azurite..."
docker compose -f "$COMPOSE_FILE" up -d

echo "==> Waiting for MinIO..."
until curl -sf "$MINIO_ENDPOINT/minio/health/live" > /dev/null 2>&1; do sleep 1; done

echo "==> Waiting for Azurite..."
until curl -s --max-time 2 "$AZURITE_ENDPOINT/" > /dev/null 2>&1; do sleep 1; done

echo "==> Waiting for fake-gcs-server..."
until curl -s --max-time 2 "$FAKE_GCS_ENDPOINT/storage/v1/b" > /dev/null 2>&1; do sleep 1; done

cd "$BACKEND"

echo "==> Seeding all three emulators with orders.{json,csv,parquet,xlsx}..."
uv run python - << 'PYEOF'
import io, json, os, pathlib

import duckdb
import httpx
import s3fs
from azure.storage.blob import BlobServiceClient

SRC = pathlib.Path("tests/scenarios/fixtures/orders.json")
BUCKET = "dte-test"

# Render the one fixture into every format DTE can read, so each
# (format x backend) source in the test matrix has real data behind it.
# DuckDB does the conversion — same readers/writers the product uses.
tmp = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "dte-seed"
tmp.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute("INSTALL excel"); con.execute("LOAD excel")
con.execute(f"CREATE TABLE orders AS SELECT * FROM read_json_auto('{SRC}')")
for name, clause in [
    ("orders.csv", "FORMAT CSV, HEADER"),
    ("orders.parquet", "FORMAT PARQUET"),
    ("orders.xlsx", "FORMAT xlsx, HEADER true"),
]:
    con.execute(f"COPY orders TO '{tmp / name}' ({clause})")

payloads = {"orders.json": SRC.read_bytes()}
for name in ("orders.csv", "orders.parquet", "orders.xlsx"):
    payloads[name] = (tmp / name).read_bytes()

# ── MinIO (S3) ───────────────────────────────────────────────────────────
fs = s3fs.S3FileSystem(
    key="minioadmin", secret="minioadmin",
    client_kwargs={"endpoint_url": os.environ["MINIO_ENDPOINT"]},
    use_ssl=False,
)
try:
    fs.mkdirs(BUCKET, exist_ok=True)
except Exception:
    pass
for name, blob in payloads.items():
    with fs.open(f"{BUCKET}/{name}", "wb") as f:
        f.write(blob)
print(f"seeded: s3://{BUCKET}/{{{','.join(payloads)}}}")

# ── fake-gcs-server ──────────────────────────────────────────────────────
# Seeded over the JSON upload API, which every fake-gcs build supports.
# Writes back out go over the XML PUT, which only the PR #2092 build has —
# see docker/docker-compose.storage-test.yml and plans/045.
base = os.environ["FAKE_GCS_ENDPOINT"]
r = httpx.post(f"{base}/storage/v1/b?project=test", json={"name": BUCKET})
if r.status_code not in (200, 409):
    raise RuntimeError(f"bucket create failed: {r.status_code} {r.text}")
for name, blob in payloads.items():
    r = httpx.post(
        f"{base}/upload/storage/v1/b/{BUCKET}/o?uploadType=media&name={name}",
        content=blob, headers={"Content-Type": "application/octet-stream"},
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"upload {name} failed: {r.status_code} {r.text}")
print(f"seeded: gcs://{BUCKET}/{{{','.join(payloads)}}}")

# ── Azurite ──────────────────────────────────────────────────────────────
client = BlobServiceClient.from_connection_string(os.environ["AZURITE_CONN"])
try:
    client.create_container(BUCKET)
except Exception:
    pass  # already exists
for name, blob in payloads.items():
    client.get_blob_client(BUCKET, name).upload_blob(blob, overwrite=True)
print(f"seeded: az://{BUCKET}/{{{','.join(payloads)}}}")
PYEOF

if [[ "$MODE" == "start" ]]; then
  cat <<EOF

==> Emulators are UP and seeded (containers left running).

  MinIO      S3        $MINIO_ENDPOINT      (console :9001, minioadmin/minioadmin)
  Azurite    Azure     $AZURITE_ENDPOINT
  fake-gcs   GCS       $FAKE_GCS_ENDPOINT   (reads + writes; needs the PR #2092 image)

  Bucket/container 'dte-test' holds orders.{json,csv,parquet,xlsx}.

  Stop with: $0 stop
EOF
  exit 0
fi

echo "==> Running integration tests..."
uv run pytest tests/integration/test_cloud_storage.py -m integration -v -s

echo "==> Done."
