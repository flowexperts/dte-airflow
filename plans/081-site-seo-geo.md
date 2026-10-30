# 081 — Site SEO and GEO

## Problem

The marketing site and docs are crawlable static HTML, but:

- Child pages inherit the homepage's `openGraph`/`twitter` block, so a shared
  `/use-cases/x/` link previews with the homepage title, description and URL.
- JSON-LD uses a non-schema.org `applicationCategory`, has no publisher, and
  the landing FAQ has no `FAQPage` markup that answer engines can lift.
- VitePress docs have no canonical or Open Graph tags.
- `llms.txt` lists none of the site's pages, sends docs readers to GitHub, uses
  a relative link, and there is no `llms-full.txt` or Markdown copy of the docs.

## Change

- `site/src/lib/site.ts`: `pageMeta(title, description, path)` builds
  title/description/canonical/openGraph/twitter for every page.
- `layout.tsx`: JSON-LD `DeveloperApplication`, publisher, requirements,
  download URL.
- `landing-page.tsx`: `FAQPage` JSON-LD from the FAQ list.
- `docs-vp/.vitepress/config.mts`: `vitepress-plugin-llms` (writes
  `/docs/llms.txt`, `/docs/llms-full.txt` and per-page `.md`), canonical + OG
  tags per page.
- `public/llms.txt`: absolute links to every page and docs section.

Branch: `feature/site-seo`. Not changed: page copy (H1 wording is a copy call).
