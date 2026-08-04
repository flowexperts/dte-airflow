# site — DTE marketing landing page

Standalone, statically-exported Next.js app for the public beta-launch landing page.
Decoupled from `frontend/` (the product app) — no backend, no auth, no SWR. Deploys
to Cloudflare Pages as static HTML/CSS/JS.

## Develop

```bash
cd site
pnpm install
cp .env.local.example .env.local   # set NEXT_PUBLIC_APP_URL / NEXT_PUBLIC_SITE_URL
pnpm dev   # http://localhost:3001 (see package.json if you wire a custom port)
```

## Build & deploy (Cloudflare Pages)

Auto-deploy is wired via `.github/workflows/deploy-site.yml` — pushes to `main`
that touch `site/**` build and run `wrangler pages deploy` automatically.
One-time setup, before the first push:

1. Create the Cloudflare Pages project once (`npx wrangler pages project create dte-site`,
   or via the dashboard) so the workflow has something to deploy into.
2. Add repo secrets: `CLOUDFLARE_API_TOKEN` (Pages:Edit scope) and `CLOUDFLARE_ACCOUNT_ID`.
3. Add repo variables `DTE_APP_URL` (real app URL) and `DTE_SITE_URL` (this
   site's real domain, e.g. `https://dte.dev`) — both fall back to `*.example.com`
   placeholders if unset. `DTE_SITE_URL` feeds `metadataBase`, canonical links,
   Open Graph/Twitter tags, `sitemap.xml`, and `robots.txt`'s `Sitemap:` line, so
   it should be set before the first real launch.

Manual deploy (no CI):

```bash
pnpm build          # next build with output: "export" → writes static site to out/
npx wrangler pages deploy out --project-name=dte-site
```

## What's here

- `src/app/page.tsx` renders `LandingPage` from `src/components/marketing/`.
- `src/components/marketing/` — copied from `frontend/src/components/marketing/`
  (hero, flow diagram, steps grid, quality panel, Cal.com booking embed, custom
  video player). Kept as a separate copy on purpose — this project has no shared
  package boundary with `frontend/`, and the two are free to diverge.
- `public/marketing/` — demo video assets, copied from `frontend/public/marketing/`.
- No `ThemeProvider`/`SwrProvider`/auth — the marketing site is always dark-themed
  and makes zero API calls. The "Open app" link points at `NEXT_PUBLIC_APP_URL`.

If you edit the shared marketing copy in `frontend/`, mirror the change here (and
vice versa) — there's no build-time link between the two.

## SEO / GEO

- `src/lib/site.ts` — single source of truth for site URL/name/title/description,
  used by every metadata surface below. Update the description here to change it
  everywhere at once.
- `src/app/layout.tsx` — full `<head>` metadata: title template, description,
  keywords, canonical, Open Graph, Twitter card, plus a `SoftwareApplication`
  JSON-LD block (structured data for search rich results and AI answer engines).
- `src/app/opengraph-image.tsx` — generates the OG/Twitter share image at build
  time (`next/og`, brand colors, no external asset). Twitter falls back to this
  automatically since no separate `twitter-image` is defined.
- `src/app/sitemap.ts` / `src/app/robots.ts` — generated `sitemap.xml` /
  `robots.txt` (the latter points at the former). Both need `dynamic = "force-static"`
  to work under `output: "export"`.
- `public/llms.txt` — plain-text summary of what DTE is/does, following the
  emerging `llms.txt` convention so AI assistants and answer engines (GEO) can
  accurately describe the product without having to parse the rendered page.
- The page itself is a single static, fully server-rendered `<main>` with one
  `<h1>` and real text content (steps, sources/destinations, quality checks) —
  no client-side-only rendering gate, so both search crawlers and LLM browsing
  tools see the full content on first load.
