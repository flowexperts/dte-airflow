# 106 — Versioned docs and release notes

## Problem

`/docs/` always renders `docs/user` from the deployed branch head, so someone on
`dte-airflow==0.1.0` reads docs for unreleased code. There are no release notes,
though `self-hosting/upgrading.md` already tells people to read them.

## Change

- `docs/user/releases.md`: one `## vX.Y.Z — date` section per release, newest
  first. Linked in the sidebar.
- `release.yml` refuses a tag whose version has no section there.
- `/docs/` keeps rendering the branch head ("latest"). `site/scripts/build-versioned-docs.sh`
  builds `docs/user` as it was at every `v*` tag into `/docs/<tag>/`, using the
  current VitePress config (`DOCS_VERSION`, `DOCS_SRC` env). A nav dropdown
  links the versions.
- `deploy-site.yml` checks out with full history so tags are there.

## Tasks (branch `feature/versioned-docs`)

1. releases.md + sidebar link + upgrading.md link
2. config env overrides, version dropdown, build script, `pnpm build` runs it
3. release.yml guard, deploy-site fetch-depth

## Files

- `docs/user/releases.md` (new), `docs/user/self-hosting/upgrading.md`
- `site/docs-vp/.vitepress/config.mts`, `site/package.json`
- `site/scripts/build-versioned-docs.sh` (new)
- `.github/workflows/release.yml`, `.github/workflows/deploy-site.yml`
