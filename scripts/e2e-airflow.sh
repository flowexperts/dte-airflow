#!/usr/bin/env bash
# End-to-end check of DTE inside Airflow against a running `docker compose up`.
# Creates a connection, source, destination, a transform and a failing quality
# pipeline, runs both through Airflow, and checks the results.
set -euo pipefail
A=${AIRFLOW_URL:-http://localhost:8080}
T=$(curl -sf -X POST "$A/auth/token" -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
H=(-H "Authorization: Bearer $T" -H 'content-type: application/json')
mkdir -p /tmp/dte-samples/e2e && rm -f /tmp/dte-samples/e2e/out.json
echo '[{"age":5},{"age":30},{"age":40}]' > /tmp/dte-samples/e2e/in.json

curl -s "${H[@]}" -X POST "$A/api/v2/connections" -d '{"connection_id":"e2e_fs","conn_type":"fs","extra":"{}"}' >/dev/null
curl -sf "${H[@]}" -X POST "$A/dte/api/sources" -d '{"id":"e2e_src","connection_id":"e2e_fs","source_type":"filesystem","config":{"bucket_url":"/tmp/dte-samples/e2e","file_glob":"in.json"},"table":"t","format":"json"}' >/dev/null || true
curl -sf "${H[@]}" -X POST "$A/dte/api/destinations" -d '{"id":"e2e_out","connection_id":"e2e_fs","config":{"type":"json","path":"/tmp/dte-samples/e2e/out.json"}}' >/dev/null || true
curl -sf "${H[@]}" -X POST "$A/dte/api/pipelines" -d '{"id":"e2e_t","name":"e2e t","sources":["e2e_src"],"output_id":"e2e_out","steps":[{"op":"filter","expr":"age > 18"}]}' >/dev/null || true
curl -sf "${H[@]}" -X POST "$A/dte/api/pipelines" -d '{"id":"e2e_q","name":"e2e q","sources":["e2e_src"],"pipeline_type":"quality","output_id":null,"steps":[{"op":"check","expr":"age > 18","severity":"fail","label":"adult"}]}' >/dev/null || true

run() {  # trigger (waits for the DAG to be parsed) then poll to a terminal status
  local rid st
  rid=$(curl -sf "${H[@]}" -X POST "$A/dte/api/pipelines/$1/trigger" -d '{}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["run_id"])')
  for _ in $(seq 60); do
    st=$(curl -sf "${H[@]}" "$A/dte/api/runs/$rid" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["status"],d["rows_written"])')
    case "$st" in pending*|running*) sleep 2;; *) echo "$st"; return;; esac
  done
  echo "timeout"
}

t=$(run e2e_t); echo "transform: $t"; [[ "$t" == "completed 2" ]]
grep -q '"age":40' /tmp/dte-samples/e2e/out.json
q=$(run e2e_q); echo "quality:   $q"; [[ "$q" == failed_quality* ]]
curl -sf -o /dev/null "$A/dte/ui/dte.umd.js"  # the react_apps bundle (plan 066)
echo "E2E OK"
