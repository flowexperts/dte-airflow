#!/usr/bin/env bash
# Install the dte-airflow wheel into a stock apache/airflow image exactly as
# docs/user/self-hosting/install-plugin.md says (Airflow's constraints file,
# unmodified), then run pipelines end to end through Airflow (plans 073, 074):
#   local file -> local file, MinIO (S3) -> MinIO Parquet, Azurite -> local,
#   fake-gcs-server -> local, SFTP -> SFTP, Postgres -> Postgres.
# The S3 connection exists only as an AIRFLOW_CONN_* env var. Needs Docker,
# pnpm and uv.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
AIRFLOW=3.3.2
PY=3.12
NAME=dte-pip-smoke-$$
PORT=${PORT:-8098}
WORK=$(mktemp -d)
AZ_KEY='Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=='
AZ_CONN="DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=$AZ_KEY;BlobEndpoint=http://$NAME-azurite:10000/devstoreaccount1;"
MINIO="http://$NAME-minio:9000"

cleanup() {
  docker rm -f "$NAME-af" "$NAME-pg" "$NAME-minio" "$NAME-azurite" "$NAME-gcs" "$NAME-sftp" >/dev/null 2>&1 || true
  docker network rm "$NAME" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "== build UI + wheel"
(cd "$ROOT/frontend" && pnpm build >/dev/null 2>&1)
rm -rf "$ROOT/backend/dte/ui" && cp -r "$ROOT/frontend/dist" "$ROOT/backend/dte/ui"
(cd "$ROOT/backend" && uv build --wheel -q -o "$WORK")
WHEEL=$(basename "$WORK"/dte_airflow-*.whl)

mkdir -p "$WORK/dags" "$WORK/data" "$WORK/gcs/lake/in" "$WORK/sftp"
cat > "$WORK/dags/dte_dags.py" <<'EOF'
from dte.airflow.dag_factory import build_dags

globals().update(build_dags())
EOF
echo '[{"id":1,"amount":50},{"id":2,"amount":150},{"id":3,"amount":250}]' > "$WORK/data/orders.json"
cp "$WORK/data/orders.json" "$WORK/gcs/lake/in/"; cp "$WORK/data/orders.json" "$WORK/sftp/"
chmod -R a+rwX "$WORK"

echo "== postgres, minio, azurite, fake-gcs, sftp, airflow $AIRFLOW"
docker network create "$NAME" >/dev/null
docker run -d --name "$NAME-pg" --network "$NAME" -e POSTGRES_USER=airflow \
  -e POSTGRES_PASSWORD=airflow -e POSTGRES_DB=airflow postgres:16-alpine >/dev/null
docker run -d --name "$NAME-minio" --network "$NAME" -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin minio/minio:latest server /data >/dev/null
docker run -d --name "$NAME-azurite" --network "$NAME" mcr.microsoft.com/azure-storage/azurite:latest \
  azurite-blob --blobHost 0.0.0.0 --blobPort 10000 --skipApiVersionCheck >/dev/null
docker run -d --name "$NAME-gcs" --network "$NAME" -v "$WORK/gcs:/data" fsouza/fake-gcs-server \
  -scheme http -port 4443 -public-host "$NAME-gcs:4443" >/dev/null
docker run -d --name "$NAME-sftp" --network "$NAME" -v "$WORK/sftp:/home/foo/in" atmoz/sftp foo:pass:::in >/dev/null
until docker exec "$NAME-pg" pg_isready -U airflow -d airflow >/dev/null 2>&1; do sleep 1; done
sleep 2  # pg_isready passes during initdb's restart
docker exec "$NAME-pg" psql -qU airflow -d airflow -c 'CREATE DATABASE wh' >/dev/null
docker exec "$NAME-pg" psql -qU airflow -d wh -c "CREATE TABLE orders(id int, amount int); INSERT INTO orders VALUES (1,50),(2,150),(3,250)" >/dev/null
# DTE gets its own database and role, with no way into Airflow's (plan 075).
docker exec "$NAME-pg" psql -qU airflow -d airflow -c "CREATE ROLE dte LOGIN PASSWORD 'dte'" \
  -c 'CREATE DATABASE dte OWNER dte' -c 'REVOKE CONNECT ON DATABASE airflow FROM PUBLIC' >/dev/null
docker exec -e PGPASSWORD=dte "$NAME-pg" psql -h localhost -U dte -d airflow -c 'SELECT 1' >/dev/null 2>&1 \
  && { echo "FAIL: the dte role can reach the airflow database"; exit 1; }

MINIO_CONN=$(python3 -c "import json;print(json.dumps({'conn_type':'aws','login':'minioadmin','password':'minioadmin','extra':{'endpoint_url':'$MINIO'}}))")
docker run -d --name "$NAME-af" --network "$NAME" -p "127.0.0.1:$PORT:8080" \
  -v "$WORK:/smoke" \
  -e OPENSSL_armcap=0 \
  `# gcsfs's default gRPC path does TLS, which the plain-HTTP GCS emulator can't answer` \
  -e GCSFS_EXPERIMENTAL_ZB_HNS_SUPPORT=false \
  -e AIRFLOW__CORE__EXECUTOR=LocalExecutor \
  -e AIRFLOW__CORE__LOAD_EXAMPLES=False \
  -e AIRFLOW__CORE__TEST_CONNECTION=Enabled \
  -e AIRFLOW__CORE__DAGS_FOLDER=/smoke/dags \
  -e AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql+psycopg2://airflow:airflow@$NAME-pg/airflow \
  -e AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_USERS=admin:admin \
  -e AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE=/smoke/passwords.json \
  -e AIRFLOW__DAG_PROCESSOR__REFRESH_INTERVAL=5 \
  -e "AIRFLOW_CONN_MINIO=$MINIO_CONN" \
  -e DTE_DATABASE_URL=postgresql://dte:dte@$NAME-pg/dte \
  -e DTE_ARTIFACT_DIR=/tmp/dte-artifacts \
  "apache/airflow:$AIRFLOW-python$PY" bash -c "
    set -e
    echo '{\"admin\": \"admin\"}' > /smoke/passwords.json
    curl -fsSL https://raw.githubusercontent.com/apache/airflow/constraints-$AIRFLOW/constraints-$PY.txt -o /tmp/constraints.txt
    # Flaky networks surface as pip 'ResolutionImpossible'; retry the install.
    for i in 1 2 3; do
      pip install -q --retries 10 --timeout 60 --constraint /tmp/constraints.txt '/smoke/$WHEEL[amazon,sftp,models]' && break
      [ \$i = 3 ] && exit 1; sleep 5
    done
    airflow db migrate
    dte db upgrade
    exec airflow standalone" >/dev/null

BASE=http://localhost:$PORT
fail() { echo "FAIL: $*"; docker logs --tail 80 "$NAME-af" 2>&1 | grep -v "request finished"; exit 1; }
check() { echo "ok   $*"; }

echo -n "== waiting for the api-server"
for _ in $(seq 1 120); do
  curl -fs "$BASE/api/v2/version" >/dev/null 2>&1 && break
  docker inspect -f '{{.State.Running}}' "$NAME-af" | grep -q true || fail "airflow exited"
  echo -n .; sleep 5
done
echo
curl -fs "$BASE/api/v2/version" >/dev/null || fail "api-server never came up"

docker exec -e AZ_CONN="$AZ_CONN" "$NAME-af" python -c "
import boto3, os
from azure.storage.blob import BlobServiceClient
data = open('/smoke/data/orders.json', 'rb').read()
s3 = boto3.client('s3', endpoint_url='$MINIO', aws_access_key_id='minioadmin', aws_secret_access_key='minioadmin')
s3.create_bucket(Bucket='lake'); s3.put_object(Bucket='lake', Key='in/2026/orders.json', Body=data)
az = BlobServiceClient.from_connection_string(os.environ['AZ_CONN'])
az.create_container('lake'); az.get_blob_client('lake', 'in/orders.json').upload_blob(data)
" && check "MinIO and Azurite seeded" || fail "seeding"

TOKEN=$(curl -fs -X POST "$BASE/auth/token" -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin"}' | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
AUTH=(-H "Authorization: Bearer $TOKEN" -H 'content-type: application/json')
post() { curl -fsS "${AUTH[@]}" -X POST "$BASE$1" -d "$2" >/dev/null; }
get() { curl -fs "${AUTH[@]}" "$BASE$1"; }

get /api/v2/plugins | grep -q '"name":"dte"' && check "plugin registered" || fail "plugin missing"
curl -fs "$BASE/dte/ui/dte.umd.js" -o /dev/null && check "UI bundle served" || fail "UI bundle not served"

CAPS=$(get /dte/api/capabilities)
python3 - "$CAPS" <<'EOF' && check "capabilities follow installed providers" || fail "capabilities: $CAPS"
import json, sys
k = json.loads(sys.argv[1])["connection_kinds"]
assert k["s3"]["available"] and k["azure"]["available"] and k["postgres"]["available"], k
assert not k["mongodb"]["available"] and k["mongodb"]["install"] == "apache-airflow-providers-mongo", k
EOF

post /api/v2/connections '{"connection_id":"local_fs","conn_type":"fs"}' || fail "fs connection"
WASB=$(AZ_CONN="$AZ_CONN" python3 -c "import json, os; print(json.dumps(dict(connection_id='azurite', conn_type='wasb', extra=json.dumps(dict(connection_string=os.environ['AZ_CONN'])))))")
post /api/v2/connections "$WASB" \
  || fail "wasb connection"
GCP=$(python3 -c "import json;print(json.dumps(dict(connection_id='fakegcs', conn_type='google_cloud_platform', extra=json.dumps({'is_anonymous': True, 'project': 'test', 'gcs.endpoint': 'http://$NAME-gcs:4443'}))))")
post /api/v2/connections "$GCP" || fail "gcp connection"
post /api/v2/connections "{\"connection_id\":\"sftp\",\"conn_type\":\"sftp\",\"host\":\"$NAME-sftp\",\"port\":22,\"login\":\"foo\",\"password\":\"pass\",\"extra\":\"{\\\"no_host_key_check\\\": \\\"true\\\"}\"}" || fail "sftp connection"
post /api/v2/connections "{\"connection_id\":\"wh\",\"conn_type\":\"postgres\",\"host\":\"$NAME-pg\",\"port\":5432,\"login\":\"airflow\",\"password\":\"airflow\",\"schema\":\"wh\"}" || fail "postgres connection"
CONNS=$(get /dte/api/connections)
python3 -c "import json,sys;ids={c['id']:c['connection_type'] for c in json.loads(sys.argv[1])};assert ids.get('minio')=='s3' and ids.get('azurite')=='azure' and ids.get('fakegcs')=='gcs' and ids.get('sftp')=='sftp' and ids.get('wh')=='postgres',ids" "$CONNS" \
  && check "env-var (minio) and DB (azurite) connections listed" || fail "connections: $CONNS"
PROBE=$(curl -fs "${AUTH[@]}" -X POST "$BASE/dte/api/connections/minio/test")
echo "info S3 connection test via the provider: $PROBE"

post /dte/api/sources '{"id":"orders","source_type":"filesystem","connection_id":"local_fs","config":{"bucket_url":"/smoke/data","file_glob":"orders.json"},"table":"orders"}' || fail "local source"
post /dte/api/sources '{"id":"s3_orders","source_type":"s3","connection_id":"minio","config":{"bucket_url":"s3://lake/in","file_glob":"**/*.json"},"table":"s3_orders"}' || fail "s3 source"
post /dte/api/sources '{"id":"az_orders","source_type":"azure","connection_id":"azurite","config":{"bucket_url":"az://lake/in","file_glob":"*.json"},"table":"az_orders"}' || fail "azure source"
post /dte/api/destinations '{"id":"out","connection_id":"local_fs","config":{"type":"json","path":"/smoke/data/out.json"}}' || fail "local destination"
post /dte/api/destinations '{"id":"s3_out","connection_id":"minio","config":{"type":"parquet","path":"s3://lake/out/big.parquet"}}' || fail "s3 destination"
post /dte/api/destinations '{"id":"az_out","connection_id":"local_fs","config":{"type":"json","path":"/smoke/data/az_out.json"}}' || fail "az destination"
post /dte/api/sources '{"id":"gcs_orders","source_type":"gcs","connection_id":"fakegcs","config":{"bucket_url":"gs://lake/in","file_glob":"*.json"},"table":"gcs_orders"}' || fail "gcs source"
post /dte/api/sources '{"id":"sftp_orders","source_type":"sftp","connection_id":"sftp","config":{"bucket_url":"sftp:///in","file_glob":"orders.json"},"table":"sftp_orders"}' || fail "sftp source"
post /dte/api/sources '{"id":"pg_orders","source_type":"sql_database","connection_id":"wh","config":{},"table":"pg_orders"}' || fail "postgres source"
post /dte/api/destinations '{"id":"gcs_out","connection_id":"local_fs","config":{"type":"json","path":"/smoke/data/gcs_out.json"}}' || fail "gcs destination"
post /dte/api/destinations '{"id":"sftp_out","connection_id":"sftp","config":{"type":"json","path":"sftp:///in/big.json"}}' || fail "sftp destination"
post /dte/api/destinations '{"id":"pg_out","connection_id":"wh","config":{"type":"postgres","schema":"public","table":"big_orders"}}' || fail "postgres destination"
pipeline() { post /dte/api/pipelines "{\"id\":\"$1\",\"name\":\"$1\",\"sources\":[{\"source_id\":\"$2\",\"alias\":\"o\"${4:+,\"table\":\"$4\"}}],\"steps\":[{\"op\":\"filter\",\"expr\":\"amount > 100\"}],\"output_id\":\"$3\"}" || fail "pipeline $1"; }
pipeline local orders out; pipeline s3 s3_orders s3_out; pipeline az az_orders az_out
pipeline gcs gcs_orders gcs_out; pipeline sftp sftp_orders sftp_out; pipeline pg pg_orders pg_out orders
check "sources, destinations, pipelines created"

run() {  # pipeline id: wait for its DAG, trigger, wait for completion
  local id=$1 dag="" status="" run_id
  for _ in $(seq 1 30); do dag=$(get "/api/v2/dags/dte__$id" || true); [ -n "$dag" ] && break; sleep 3; done
  [ -n "$dag" ] || fail "dte__$id never parsed: $(get /api/v2/importErrors)"
  echo "$dag" | grep -q '"is_paused":false' || fail "dte__$id is paused"
  run_id=$(curl -fs "${AUTH[@]}" -X POST "$BASE/dte/api/pipelines/$id/trigger" -d '{}' \
    | python3 -c 'import json,sys;print(json.load(sys.stdin)["run_id"])') || fail "trigger $id"
  for _ in $(seq 1 40); do
    status=$(get "/dte/api/runs/$run_id" | python3 -c 'import json,sys;print(json.load(sys.stdin)["status"])')
    case $status in completed|failed*) break ;; esac
    sleep 3
  done
  [ "$status" = completed ] || fail "run $id: $(get "/dte/api/runs/$run_id")"
}
ids_in() { python3 -c "import json;r=json.load(open('$1'));assert sorted(x['id'] for x in r)==[2,3],r"; }

run local; ids_in "$WORK/data/out.json" && check "local file -> local file" || fail "local output"
run s3
docker exec "$NAME-af" python -c "
import boto3, io, pyarrow.parquet as pq
s3 = boto3.client('s3', endpoint_url='$MINIO', aws_access_key_id='minioadmin', aws_secret_access_key='minioadmin')
t = pq.read_table(io.BytesIO(s3.get_object(Bucket='lake', Key='out/big.parquet')['Body'].read()))
assert sorted(t.column('id').to_pylist()) == [2, 3], t
import os; os._exit(0)  # pyarrow can abort during interpreter teardown
" && check "S3 read (** glob) + Parquet write through the amazon provider" || fail "s3 output"
run az; ids_in "$WORK/data/az_out.json" && check "Azure read through the microsoft-azure provider" || fail "azure output"

run gcs; ids_in "$WORK/data/gcs_out.json" && check "GCS read through the google provider" || fail "gcs output"
run sftp; ids_in "$WORK/sftp/big.json" && check "SFTP read + write through the sftp provider" || fail "sftp output"
run pg
[ "$(docker exec "$NAME-pg" psql -tAU airflow -d wh -c 'SELECT id FROM public.big_orders ORDER BY id' | paste -sd, -)" = "2,3" ] \
  && check "Postgres -> Postgres through the postgres provider hook" || fail "postgres output"

RUNS=$(get "/dte/api/pipelines/pg/runs")
python3 -c "import json,sys;r=json.loads(sys.argv[1]);assert len(r)==1 and r[0]['status']=='completed' and r[0]['rows_written']==2,r" "$RUNS" \
  && check "run history merges Airflow dag runs with DTE's own database" || fail "runs: $RUNS"

echo "PASS"
