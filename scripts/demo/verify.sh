#!/usr/bin/env bash
#
# Verify the demo warehouse, all four demo pipelines and the dashboard before
# a recording session. Run this instead of discovering a broken beat with the camera
# rolling.
#
#   ./scripts/demo/verify.sh
#
# Assumes `docker compose up -d --build` has been run from this directory.
# Exits non-zero on the first failure.

set -euo pipefail

API="${DTE_URL:-http://localhost:8001}"
EMAIL="${DTE_EMAIL:-demo@example.com}"
PASSWORD="${DTE_PASSWORD:-demopass1234}"
COMPOSE="docker compose -p ${COMPOSE_PROJECT_NAME:-dte}"

ok()   { printf '  \033[32m✓\033[0m %s\n'  "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n'  "$1"; exit 1; }
step() { printf '\n\033[36m%s\033[0m\n' "$1"; }

psql_demo() { $COMPOSE exec -T postgres-demo psql -U demo -d warehouse -tAc "$1"; }

# ── 1. services ───────────────────────────────────────────────────────────
step "1. services"
for i in $(seq 1 40); do
  $COMPOSE exec -T postgres-demo pg_isready -U demo -d warehouse >/dev/null 2>&1 && break
  sleep 2
done
$COMPOSE exec -T postgres-demo pg_isready -U demo -d warehouse >/dev/null 2>&1 \
  || fail "postgres-demo not ready (docker compose up -d postgres-demo)"
ok "postgres-demo ready"

for i in $(seq 1 40); do curl -sf "$API/healthz" >/dev/null 2>&1 && break; sleep 2; done
curl -sf "$API/healthz" >/dev/null 2>&1 || fail "backend not healthy at $API"
ok "backend healthy"

# ── 2. warehouse seed ─────────────────────────────────────────────────────
step "2. warehouse seed"
expect_rows() {
  local got; got=$(psql_demo "select count(*) from $1;")
  [ "$got" -eq "$2" ] || fail "$1 has $got rows, expected $2 (reseed: $COMPOSE rm -sfv postgres-demo && docker volume rm ${COMPOSE_PROJECT_NAME:-dte}_demo_pgdata)"
  ok "$1: $got rows"
}
expect_rows crm.customers      800
expect_rows crm.regions          6
expect_rows sales.products      40
expect_rows sales.orders     12000
expect_rows sales.order_items 30000
expect_rows sales.vendor_bills   5

# The Auto-map demo maps onto these 13 columns. If a bare run of the
# order_facts pipeline (one with no select step) ever lands, dlt's schema
# evolution appends ~28 intermediate columns here and never removes them.
cols=$(psql_demo "select count(*) from information_schema.columns where table_schema='analytics' and table_name='order_facts';")
[ "$cols" -eq 13 ] || fail "analytics.order_facts has $cols columns, expected 13 — a select-less run polluted it; drop the demo_pgdata volume"
ok "analytics.order_facts: 13 columns (schema not polluted)"

# ── 3. seed the control plane ─────────────────────────────────────────────
step "3. seed connections / sources / destinations / pipelines"
python3 scripts/demo/seed-demo.py >/tmp/dte-seed.log 2>&1 \
  || { cat /tmp/dte-seed.log; fail "seed-demo.py failed"; }
ok "seeded"
# Idempotence is not decoration: the recordings re-run this between takes.
python3 scripts/demo/seed-demo.py >/tmp/dte-seed2.log 2>&1 \
  || { cat /tmp/dte-seed2.log; fail "seed-demo.py is not idempotent — second run failed"; }
ok "second run clean (idempotent)"

TOKEN=$(curl -sf -X POST "$API/api/auth/login" -H 'Content-Type: application/json' \
        -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
        | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"

curl -sf -X POST "$API/api/connections/demo_warehouse/test" -H "$AUTH" \
  | grep -q '"ok":true' || fail "connection demo_warehouse failed its test probe"
ok "connection demo_warehouse reachable from the backend container"

# ── 4. pipelines ──────────────────────────────────────────────────────────
step "4. pipeline runs"
run_pipeline() {  # name, trigger-body, expected-rows
  local rid
  rid=$(curl -sf -X POST "$API/api/pipelines/$1/trigger" -H "$AUTH" \
        -H 'Content-Type: application/json' -d "$2" \
        | python3 -c 'import sys,json;print(json.load(sys.stdin)["run_id"])')
  for _ in $(seq 1 120); do
    curl -sf "$API/api/runs/$rid" -H "$AUTH" -o /tmp/dte-run.json
    local status
    status=$(python3 -c "import json;print(json.load(open('/tmp/dte-run.json',encoding='utf-8')).get('status'))")
    case "$status" in
      completed)
        local rows
        rows=$(python3 -c "import json;print(json.load(open('/tmp/dte-run.json',encoding='utf-8')).get('rows_written'))")
        [ "$rows" = "$3" ] || fail "$1 wrote $rows rows, expected $3"
        ok "$1: completed, $rows rows"
        return;;
      failed)
        python3 -c "import json;print(str(json.load(open('/tmp/dte-run.json',encoding='utf-8')).get('error'))[:800])"
        fail "$1: run failed";;
    esac
    sleep 2
  done
  fail "$1: run did not reach a terminal state"
}

run_pipeline demo_order_facts_pipeline '{"params":{"min_order_date":"2024-01-01"}}' 27691
run_pipeline demo_invoice_extract      '{}'                                            10

# The quality pipeline writes nothing, so it terminates in
# completed_with_warnings rather than completed: two checks pass and the
# variance check flags exactly 2 rows, because the eval corpus ships two PDFs
# per invoice number and the INV-1004 / INV-1005 pairs disagree with the
# vendor bill on purpose. Green here would mean the check stopped checking.
run_quality() {  # pipeline-id, expected status
  local rid
  rid=$(curl -sf -X POST "$API/api/pipelines/$1/trigger" -H "$AUTH" \
        -H 'Content-Type: application/json' -d '{}' \
        | python3 -c 'import sys,json;print(json.load(sys.stdin)["run_id"])')
  for _ in $(seq 1 120); do
    curl -sf "$API/api/runs/$rid" -H "$AUTH" -o /tmp/dte-run.json
    local status
    status=$(python3 -c "import json;print(json.load(open('/tmp/dte-run.json',encoding='utf-8')).get('status'))")
    case "$status" in
      completed|completed_with_warnings|failed_quality)
        [ "$status" = "$2" ] || fail "$1: status $status, expected $2"
        curl -sf "$API/api/runs/$rid/quality" -H "$AUTH" -o /tmp/dte-quality.json \
          || fail "$1: no quality detail for run $rid"
        python3 - <<'PY' || fail "$1: check steps produced no results"
import json, sys
body = json.load(open('/tmp/dte-quality.json', encoding='utf-8'))
results = body.get("results") or []
if len(results) != 3:
    print(f"  {len(results)} check results, expected 3")
    sys.exit(1)
for r in results:
    mark = "\033[32m OK \033[0m" if r.get("passed") else "\033[33mWARN\033[0m"
    print(f"  {mark} {r.get('label')}: {r.get('detail') or 'passed'}")
warned = [r for r in results if not r.get("passed")]
if len(warned) != 1:
    print(f"  {len(warned)} failing checks, expected exactly 1 (the variance check)")
    sys.exit(1)
PY
        ok "$1: $status, 3 checks (1 warn)"
        return;;
      failed)
        python3 -c "import json;print(str(json.load(open('/tmp/dte-run.json',encoding='utf-8')).get('error'))[:800])"
        fail "$1: run failed";;
    esac
    sleep 2
  done
  fail "$1: run did not reach a terminal state"
}

run_quality demo_invoice_recon completed_with_warnings

# ── 4b. dashboard ─────────────────────────────────────────────────────────
# A tile draws GET /api/pipelines/{id}/preview, so the viz pipeline previewing
# is the whole of "the dashboard works" — there is no dashboard run.
step "4b. dashboard"
curl -sf "$API/api/dashboards/demo_revenue_overview" -H "$AUTH" -o /tmp/dte-dash.json \
  || fail "dashboard demo_revenue_overview missing (re-run seed-demo.py)"
tiles=$(python3 -c "import json;print(len(json.load(open('/tmp/dte-dash.json',encoding='utf-8'))['tiles']))")
[ "$tiles" -eq 3 ] || fail "dashboard has $tiles tiles, expected 3"
ok "dashboard: $tiles tiles"

curl -sf "$API/api/pipelines/demo_revenue_by_region/preview?limit=50" -H "$AUTH" \
  -o /tmp/dte-viz.json || fail "viz pipeline preview failed — tiles will render empty"
python3 - <<'PY' || fail "viz preview returned nothing to draw"
import json, sys
body = json.load(open('/tmp/dte-viz.json', encoding='utf-8'))
rows = body.get("rows") if isinstance(body, dict) else body
if not rows:
    sys.exit(1)
cols = set(rows[0])
missing = {"region_name", "net_revenue", "orders"} - cols
if missing:
    print(f"  preview is missing {sorted(missing)} — got {sorted(cols)}")
    sys.exit(1)
print(f"  {len(rows)} regions, top: {rows[0]['region_name']} {rows[0]['net_revenue']}")
PY
ok "viz pipeline previews the columns every tile names"

# ── 5. output sanity ──────────────────────────────────────────────────────
step "5. output sanity"
nulls=$(psql_demo "select count(*) from analytics.order_facts where order_id is null or customer_name is null or account_tier is null or gross_amount is null or size_band is null;")
[ "$nulls" -eq 0 ] || fail "$nulls order_facts rows have NULLs in mapped columns — the select step aliases are wrong"
ok "no NULLs in mapped columns"

bands=$(psql_demo "select count(distinct size_band) from analytics.order_facts;")
[ "$bands" -eq 3 ] || fail "size_band has $bands distinct values, expected 3 — the case step is not exercising every branch"
ok "case step: all 3 size_band branches populated"

disc=$(psql_demo "select count(*) from analytics.order_facts where net_amount < gross_amount;")
[ "$disc" -gt 0 ] || fail "no discounted rows — the amount_after_discount expression is a no-op"
ok "expression step: $disc rows where net < gross"

# ── 6. automap tiers ──────────────────────────────────────────────────────
# The single most fragile thing in the whole demo, and invisible until the
# dialog is open on camera. The recording needs a MIX: pre-ticked exact rows
# (>= 0.9) so it doesn't look like guesswork, and unticked llm rows so
# accepting them is a real decision. All-exact is a boring wall of green;
# all-llm reads as "the matcher failed".
step "6. automap confidence tiers"
SRC=$(psql_demo "select string_agg(column_name, ',' order by ordinal_position) from information_schema.columns where table_schema='analytics' and table_name='order_facts';")
python3 - "$API" "$TOKEN" <<'PY'
import json, sys, urllib.request

api, token = sys.argv[1], sys.argv[2]
# The pipeline's output columns just before the select step.
source = ["order_id","customer_id","ordered_at","status","currency","ship_country",
          "order_item_id","product_id","quantity","unit_price","discount_pct",
          "product_id_right","product_name","category","list_price","discontinued",
          "customer_name","email","region_code","signup_date","tier","is_active",
          "region_code_right","region_name","country","line_total",
          "amount_after_discount","order_size"]
dest = ["order_id","ordered_at","status","customer_name","region_name","quantity",
        "account_tier","product_category","gross_amount","net_amount","size_band",
        "source_system","loaded_at"]

body = json.dumps({
    "source_fields": [{"name": n, "type": "string"} for n in source],
    "dest_fields":   [{"name": n, "type": "string"} for n in dest],
    "use_llm": True,
}).encode()
req = urllib.request.Request(f"{api}/api/schema/automap", data=body,
                             headers={"Content-Type": "application/json",
                                      "Authorization": f"Bearer {token}"})
r = json.load(urllib.request.urlopen(req, timeout=90))

if r.get("llm_error"):
    print(f"  \033[31m✗\033[0m automap llm pass failed: {r['llm_error']}")
    print("     The dialog shows a gold error banner, which reads as broken on")
    print("     camera. Check the anthropic_default Airflow connection before recording.")
    sys.exit(1)

exact = [m for m in r["matches"] if m.get("confidence", 0) >= 0.9]
llm   = [m for m in r["matches"] if 0 < m.get("confidence", 0) < 0.9]
none_ = [m for m in r["matches"] if not m.get("source")]

for m in r["matches"]:
    c = m.get("confidence", 0)
    mark = "TICK" if c >= 0.9 else "    "
    print(f"  {mark} {m['dest']:18} {str(m.get('source')):24} {c:4.2f}  {m.get('via')}")

expected = {
    "account_tier": "tier", "product_category": "category",
    "gross_amount": "line_total", "net_amount": "amount_after_discount",
    "size_band": "order_size",
}
wrong = [(m["dest"], m.get("source")) for m in r["matches"]
         if m["dest"] in expected and m.get("source") != expected[m["dest"]]]

problems = []
if len(exact) < 4:
    problems.append(f"only {len(exact)} pre-ticked rows — dialog will look like guesswork")
if len(llm) < 3:
    problems.append(f"only {len(llm)} sub-0.9 rows — nothing left to decide on camera")
if not none_:
    problems.append("no unmapped rows — the honest 'I can't map this' beat is gone")
if wrong:
    problems.append(f"confidently wrong matches: {wrong}")

print(f"\n  {len(exact)} pre-ticked · {len(llm)} needs-a-click · {len(none_)} unmapped")
if problems:
    for p in problems:
        print(f"  \033[31m✗\033[0m {p}")
    print("     Retune the analytics.order_facts column names in")
    print("     scripts/demo/seed/01-warehouse.sql, then reseed and re-run.")
    sys.exit(1)
print("  \033[32m✓\033[0m tier mix is good for recording")
PY

step "all checks passed — safe to record"
