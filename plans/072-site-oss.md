# 072 — Landing site for the Airflow OSS launch

Branch: `feature/site-oss` (off `dte-airflow`)

## Problem

`site/` still sold the hosted, sales-led product: "Request access" everywhere,
and source/destination tiles (HubSpot, Salesforce, Google Sheets, NetSuite, BI
dashboards) that dte-airflow doesn't ship. With `flowexperts/dte-airflow` going
public (plan 071), the site has to point at the repo.

## Changes

- CTAs: Quickstart (primary), Docs, GitHub. The Cal.com section stays as
  "Want help in production?".
- New `#quickstart` section with the four README commands and a link to the install guide.
- Source/destination tiles match the README feature tables. The "More on request" tiles are gone.
- Hero, metadata, JSON-LD, OG image and `llms.txt` say open source, Apache-2.0
  and Airflow 3 plugin. The footer carries the ASF trademark notice.
- `src/lib/site.ts`: `REPO_URL`, `DOCS_URL`, `INSTALL_URL`.

## Files

`site/src/lib/site.ts`, `site/src/app/{layout,opengraph-image}.tsx`,
`site/src/components/marketing/{landing-page,site-chrome,use-case-page}.tsx`,
`site/src/components/marketing/landing.css`, `site/public/llms.txt`.
