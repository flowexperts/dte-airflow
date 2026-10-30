# 077 — Shorter user docs, with screenshots

## Problem

The user guide (plan 076) is accurate but wordy, and it has no screenshots:
the old ones showed the pre-Airflow app, and the tooling that took them
(`docs/user/scripts/`) targets that app too.

## Change

- Cut every page in `docs/user/` to the action or fact; no facts, commands or
  anchors other pages link to change.
- `scripts/demo/capture-docs.mjs` screenshots a running stack (Airflow UI +
  DTE plugin pages) into `docs/user/assets/`. It needs the demo pipelines
  `orders_clean` and `orders_clean_checks` to exist.
- The site renders `![](../assets/...)` images: `docs.ts` maps them to
  `/docs/assets/...` and fails the build on a missing file; `predev` /
  `prebuild` copy `docs/user/assets` into `site/public/docs/assets`
  (gitignored).

## Tasks (branch `feature/docs-concise`)

1. Capture script + 13 screenshots.
2. Image rendering in the site.
3. Rewrite the pages.

## Files

- deleted: `docs/user/scripts/*`, old `docs/user/assets/*` (incl. the unused
  `landing/dte-demo.webm`)
- added: `scripts/demo/capture-docs.mjs`, `docs/user/assets/{getting-started,pipelines,airflow,connections,sources,destinations}/*.png`
- changed: `docs/user/**/*.md`, `site/src/lib/docs.ts`, `site/package.json`,
  `site/.gitignore`, `site/src/app/docs/[[...slug]]/docs.css`,
  `scripts/demo/README.md`
