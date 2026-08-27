#!/usr/bin/env bash
# encode-web.sh <webm-glob> <out-basename> [poster-timestamp] [speed]
#   e.g. ./encode-web.sh 'out/webm/build/*.webm' out/web/dte-demo 12 2
#
# Produces the three files the marketing site's <video> needs:
#   <out>.mp4          H.264 CRF 20, +faststart — the one nearly everyone gets
#   <out>.webm         VP9 fallback for builds without H.264
#   <out>-poster.jpg   a frame from `speed`-adjusted time
#
# The mp4 is listed FIRST in the player, which is the opposite of the usual
# advice and is deliberate. "webm first because VP9 is smaller" does not hold
# on this content: at quality matching the CRF-20 mp4, VP9 came out LARGER on
# the unstructured clip (3.3M vs 3.0M), and the CRF that made it smaller (32)
# is visibly softer. Since <source> order decides, webm-first shipped the
# worse file to every Chrome user while Safari got the better one.
#
# The webm still earns its place as a fallback: Chromium builds without
# proprietary codecs cannot play H.264 at all — Playwright's bundled Chromium
# is one, which is also why nothing can verify mp4 playback locally. Browsers
# only fetch the first source they can play, so the fallback costs repo bytes
# and no user bytes.
#
# Different job from encode.sh, which makes an mp4 + a fat GIF for reviewing
# a take.
#
# Quality notes — the source is what limits this. Playwright captures VP8 at
# roughly 470kbps, so re-encoding can only avoid ADDING loss, never recover
# detail. Three things follow from that:
#
#   * No scaling. This used to resample 1512 -> 1440 for no reason at all;
#     both dimensions are already even, so H.264 is happy with the native
#     size and the resampler never runs. Biggest single win here.
#   * Low CRF. 20/28 rather than 26/34 — near-transparent against a source
#     this soft, and the halved duration at 2x pays for the bitrate.
#   * Slow presets. This runs a handful of times, not in CI.
#
# Speed is applied with setpts. At 2x a 25fps source yields 25 *distinct*
# frames per output second (every second source frame), so playback stays as
# smooth as the original — no interpolation needed.
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <webm-glob> <out-basename> [poster-timestamp] [speed]" >&2
  exit 2
fi

GLOB="$1"; OUT="$2"; POSTER_AT="${3:-3}"; SPEED="${4:-1}"
# shellcheck disable=SC2206
FILES=( $GLOB )
if [[ ${#FILES[@]} -eq 0 || ! -f "${FILES[0]}" ]]; then
  echo "no webm files match: $GLOB" >&2
  exit 1
fi
SRC="${FILES[0]}"
mkdir -p "$(dirname "$OUT")"

VF=""
if [[ "$SPEED" != "1" ]]; then
  VF="-vf setpts=PTS/${SPEED}"
  POSTER_AT=$(python3 -c "print(${POSTER_AT}/${SPEED})")
fi

# shellcheck disable=SC2086
ffmpeg -y -v error -i "$SRC" $VF \
  -c:v libx264 -crf 20 -preset veryslow -pix_fmt yuv420p -an \
  -movflags +faststart "${OUT}.mp4"

# CRF 32, not 20: this is the fallback path, and 32 is where VP9 finally
# beats the mp4 on size (28 and 30 both came out larger).
# shellcheck disable=SC2086
ffmpeg -y -v error -i "$SRC" $VF \
  -c:v libvpx-vp9 -crf 32 -b:v 0 -deadline good -cpu-used 1 \
  -row-mt 1 -tile-columns 2 -an "${OUT}.webm"

ffmpeg -y -v error -ss "$POSTER_AT" -i "$SRC" \
  -frames:v 1 -q:v 2 "${OUT}-poster.jpg"

probe() { ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height -show_entries format=duration \
  -of csv=p=0:nk=1 "$1" | tr '\n' ' '; }

echo "MP4:    ${OUT}.mp4          ($(du -h "${OUT}.mp4" | cut -f1))  $(probe "${OUT}.mp4")"
echo "WEBM:   ${OUT}.webm         ($(du -h "${OUT}.webm" | cut -f1))  fallback only"
echo "POSTER: ${OUT}-poster.jpg   ($(du -h "${OUT}-poster.jpg" | cut -f1))"
