#!/usr/bin/env bash
# One-command driver: seed demo data, then screenshot the docs pages.
# Requires the stack to be running (docker compose up -d).
set -euo pipefail

cd "$(dirname "$0")/../../.."

echo "── seeding demo data"
(cd backend && uv run python ../docs/user/scripts/seed.py)

echo "── ensuring playwright chromium is installed"
pnpm --dir frontend exec playwright install chromium >/dev/null

echo "── capturing screenshots"
NODE_PATH="$(pwd)/frontend/node_modules" \
  pnpm --dir frontend exec tsx "$(pwd)/docs/user/scripts/capture.ts"

echo "── done. new files in docs/user/assets/"
git status --short docs/user/assets/ || true
