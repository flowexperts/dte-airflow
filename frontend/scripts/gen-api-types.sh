#!/usr/bin/env bash
# Regenerate src/lib/api-types.ts from the FastAPI app's OpenAPI schema.
# No server needed: the schema comes from `app.openapi()` in Python, so this
# runs the same in CI (which fails if the committed file is stale).

set -euo pipefail
cd "$(dirname "$0")/.."

OUT="src/lib/api-types.ts"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

(cd ../backend && uv run python -c '
import json, sys
from dte.api.main import app
json.dump(app.openapi(), open(sys.argv[1], "w"))
' "$TMP/openapi.json")

./node_modules/.bin/openapi-typescript "$TMP/openapi.json" -o "$OUT"
echo "wrote $OUT"
