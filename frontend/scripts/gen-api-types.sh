#!/usr/bin/env bash
# Regenerate frontend types from the running FastAPI backend.
# Requires: uvicorn dte.api.main:app --port 8000 running.

set -euo pipefail

URL="${DTE_API_URL:-http://localhost:8000}/openapi.json"
OUT="src/lib/api-types.ts"

if ! curl -fsS "$URL" > /dev/null; then
  echo "backend not reachable at $URL — start it with:" >&2
  echo "  uvicorn dte.api.main:app --port 8000 --reload" >&2
  exit 1
fi

./node_modules/.bin/openapi-typescript "$URL" -o "$OUT"
echo "wrote $OUT"
