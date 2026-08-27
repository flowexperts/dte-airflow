#!/usr/bin/env bash
# encode-web.sh <webm-glob> <out-basename> [poster-timestamp]
#   e.g. ./encode-web.sh 'out/webm/core-join/*.webm' out/web/dte-demo 112
#
# Produces the three files the marketing site's <video> needs:
#   <out>.mp4          H.264, +faststart   (Safari, and every crawler)
#   <out>.webm         VP9                 (smaller where it is supported)
#   <out>-poster.jpg   first painted frame (what shows before autoplay starts)
#
# Different job from encode.sh, which makes an mp4 + a fat GIF for reviewing
# a take. These are downscaled to 1440 wide to match the assets already in
# site/public/marketing/ and tuned for a page that autoplays them on loop.
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <webm-glob> <out-basename> [poster-timestamp]" >&2
  exit 2
fi

GLOB="$1"; OUT="$2"; POSTER_AT="${3:-3}"
# shellcheck disable=SC2206
FILES=( $GLOB )
if [[ ${#FILES[@]} -eq 0 || ! -f "${FILES[0]}" ]]; then
  echo "no webm files match: $GLOB" >&2
  exit 1
fi
SRC="${FILES[0]}"
mkdir -p "$(dirname "$OUT")"

# -2 rather than -1 on the height: H.264 needs even dimensions, and a source
# height of 862 scales to an odd number often enough to matter.
SCALE="scale=1440:-2:flags=lanczos"

ffmpeg -y -v error -i "$SRC" -vf "$SCALE" \
  -c:v libx264 -crf 26 -preset slow -pix_fmt yuv420p -an \
  -movflags +faststart "${OUT}.mp4"

ffmpeg -y -v error -i "$SRC" -vf "$SCALE" \
  -c:v libvpx-vp9 -crf 34 -b:v 0 -row-mt 1 -an "${OUT}.webm"

# JPEG, not PNG: the poster is the landing page's LCP element, and a
# screenshot-like frame encodes to ~70KB as JPEG versus ~400KB as PNG. There
# is no alpha here to preserve.
ffmpeg -y -v error -ss "$POSTER_AT" -i "$SRC" -vf "$SCALE" \
  -frames:v 1 -q:v 3 "${OUT}-poster.jpg"

echo "MP4:    ${OUT}.mp4          ($(du -h "${OUT}.mp4" | cut -f1))"
echo "WEBM:   ${OUT}.webm         ($(du -h "${OUT}.webm" | cut -f1))"
echo "POSTER: ${OUT}-poster.jpg   ($(du -h "${OUT}-poster.jpg" | cut -f1))"
