#!/usr/bin/env bash
# Record the landing-page product demo. Same auth + seed flow as run.sh,
# but calls record.ts instead of capture.ts and post-processes the WebM
# into an MP4 that lands under frontend/public/marketing/.
set -euo pipefail

cd "$(dirname "$0")/../../.."

echo "── seeding demo data (idempotent)"
(cd backend && uv run python ../docs/user/scripts/seed.py)

echo "── ensuring playwright chromium is installed"
pnpm --dir frontend exec playwright install chromium >/dev/null

echo "── recording"
NODE_PATH="$(pwd)/frontend/node_modules" \
  pnpm --dir frontend exec tsx "$(pwd)/docs/user/scripts/record.ts"

SRC="docs/user/assets/landing/dte-demo.webm"
DEST_DIR="frontend/public/marketing"
mkdir -p "$DEST_DIR"

echo "── transcoding to mp4 (h264, muted, faststart)"
ffmpeg -y -loglevel error \
  -i "$SRC" \
  -c:v libx264 -pix_fmt yuv420p -profile:v high -crf 22 -preset veryfast \
  -movflags +faststart -an \
  "$DEST_DIR/dte-demo.mp4"

echo "── copying webm alongside for fallback"
cp "$SRC" "$DEST_DIR/dte-demo.webm"

echo "── done:"
ls -lh "$DEST_DIR"/dte-demo.*
