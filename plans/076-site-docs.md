# 076 — User docs on the site, rewritten for the Airflow app

Branch: `feature/site-docs`

## Problem

The site's **Docs** link points at `docs/user` on GitHub, which 404s while the
repo is private and reads as raw Markdown once it isn't. About two-thirds of
`docs/user` still describe the pre-Airflow app: sign-up and a DTE sidebar, a
**Trigger** button, a FastAPI process on :8001, compose-only upgrades, and an
FAQ that says scheduling doesn't exist.

## Change

- The site renders `docs/user/**/*.md` at build time under `/docs/<path>/`
  (static export, so there's no runtime). `marked` turns Markdown into HTML.
  Relative `.md` links are rewritten to site routes. The sidebar order lives
  in `site/src/lib/docs.ts`. `docs/user/scripts/` (internal) is excluded.
- `DOCS_URL` / `INSTALL_URL` point at the site pages. The sitemap lists every
  doc. `deploy-site.yml` redeploys on `docs/user/**` changes.
- Rewritten for the Airflow app: index, sign-in, first pipeline, concepts,
  building, preview & run, lookup tables, steps (15 ops), FAQ,
  troubleshooting, architecture overview, data flow, upgrading.
- Old-UI screenshots are dropped from the pages: they show the removed
  sidebar. Recapture them when `docs/user/scripts` is ported to Airflow.

## Tasks

- [ ] `site/src/lib/docs.ts`, `site/src/app/docs/[[...slug]]/page.tsx`, `docs.css`
- [ ] Rewrite the stale pages
- [ ] `pnpm typecheck && pnpm build`; every doc route exported, no broken internal links
