#!/usr/bin/env bash
# encode.sh <webm-glob> <out-basename>
#   e.g. ./encode.sh 'out/webm/user-flow/*.webm' out/demo-user-flow
#
# Produces <out-basename>.mp4 (H.264, +faststart) and <out-basename>.gif
# (960 wide, 15 fps, palettegen/paletteuse).
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <webm-glob> <out-basename>" >&2
  exit 2
fi

GLOB="$1"
OUT="$2"

# shellcheck disable=SC2206
FILES=( $GLOB )
if [[ ${#FILES[@]} -eq 0 || ! -f "${FILES[0]}" ]]; then
  echo "no webm files match: $GLOB" >&2
  exit 1
fi
SRC="${FILES[0]}"

mkdir -p "$(dirname "$OUT")"

ffmpeg -y -i "$SRC" \
  -vcodec libx264 -crf 22 -preset slow -pix_fmt yuv420p \
  -movflags +faststart "${OUT}.mp4"

ffmpeg -y -i "${OUT}.mp4" -vf \
  "fps=15,scale=960:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
  -loop 0 "${OUT}.gif"

echo ""
echo "MP4: ${OUT}.mp4  ($(du -h "${OUT}.mp4" | cut -f1))"
echo "GIF: ${OUT}.gif  ($(du -h "${OUT}.gif" | cut -f1))"
