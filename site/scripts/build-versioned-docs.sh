#!/bin/sh
# Renders docs/user as it was at every v* tag into out/docs/<tag>/ (plan 106).
# Runs after the latest build: VitePress empties its outDir first. Archives from
# the repo root: git archive in a subdirectory only takes that subdirectory.
set -eu
cd "$(dirname "$0")/.."
for tag in $(git tag -l 'v*'); do
  src=$(cd "$(mktemp -d)" && pwd -P)  # resolved: llms plugin breaks on macOS /var -> /private/var
  git -C .. archive "$tag:docs/user" | tar -x -C "$src"
  DOCS_VERSION="$tag" DOCS_SRC="$src" pnpm exec vitepress build docs-vp
  rm -rf "$src"
done
