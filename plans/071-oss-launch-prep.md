# 071 — Open-source launch prep

Branch: `feature/oss-launch-prep` (off `dte-airflow`)

## Problem

`dte-airflow` becomes its own public repo, `flowexperts/dte-airflow`, launching
at Airflow Online Connect as a beta that accepts PRs only from approved
collaborators. Four things weren't ready for that:

- The compose stack shipped a shared Fernet key, a JWT secret and `admin:admin`
  as defaults, and bound every port to `0.0.0.0`.
- `bootstrap.sh` and `.env.example` generated `DTE_*` secrets that nothing
  reads any more.
- There were no SECURITY, CONTRIBUTING, Code of Conduct or CODEOWNERS files,
  and no enforcement of the PR policy.
- CI was `workflow_dispatch`-only. The e2e job targeted the pre-Airflow
  services, and `gitleaks-action` needs a paid license on org repos.

A full-history gitleaks scan found 6 hits. All of them are Azurite's public
dev key.

## Changes

- `docker-compose.yml`: secrets and the admin password are required (`:?`);
  ports bind to `127.0.0.1`.
- `scripts/bootstrap.sh`, `.env.example`: generate and document
  `AIRFLOW_FERNET_KEY`, `AIRFLOW_JWT_SECRET` and `DTE_ADMIN_PASSWORD`.
- `LICENSE`: full Apache-2.0 text (GitHub detection), with the copyright
  moved to `NOTICE`.
- New: `SECURITY.md` (GitHub private reporting), `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `.github/CODEOWNERS`,
  `.github/workflows/pr-gate.yml` (auto-closes PRs from non-collaborators),
  `.gitleaksignore`.
- CI and security workflows run on PRs and on pushes to `main`. The stale e2e
  job is dropped, and gitleaks runs as the CLI.
- README: beta banner, new clone URL, bootstrap step, ASF trademark notice.
  `docs/user/self-hosting/install.md` is rewritten for the Airflow stack.
- Removed the stale `worktrees/ui-scaffold` gitlink.

## Manual, after the repo is created

- Set the Code of Conduct contact (`TODO-CONDUCT-EMAIL`).
- Enable private vulnerability reporting and Discussions; protect `main` with
  required CI + CODEOWNERS review and no force-push.
- `deploy-site.yml` needs the `CLOUDFLARE_*` secrets, or remove `site/`.
