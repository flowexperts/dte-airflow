# 079 — Marketing site redo (Doris-style, night + Bricolage)

## Problem

The landing page says "Data Transformation Engine. Powered by Apache Airflow"
and lists features. It doesn't speak to the Airflow team that arrives from the
Summit talk, and it never shows the builder doing anything. The approved
direction (artifact "DTE Site Vibe Check", v10) borrows Apache Doris's
rhythm: a dark, loud hero with a live product window, then paper-coloured
sections, one idea each.

## Change

- Type: Bricolage Grotesque (display + UI), Geist Mono (code). Palette: the
  flowexperts ink `#15110d` hero, ember `#e8441a` accent, cream `#f2ede4` paper.
- Landing page, top to bottom: hero ("Visual pipeline builder for Apache
  Airflow") with an animated builder → Airflow grid demo; founder note ("Why I
  built DTE"); demo video; how it works; FAQ; install + book a call.
- Use cases move to `/use-cases/` (index) and keep their detail pages,
  restyled. Integrations get their own page, `/integrations/`.
- New nav: Use cases, Integrations, Docs, GitHub, Install.
- Docs are untouched in this plan.

## Tasks (branch `feature/site-redo`)

1. `site.css` replaces `landing.css`; every rule scoped under `.site` so it
   can't leak into `/docs`.
2. Fonts in `layout.tsx` via `next/font`.
3. `site-chrome.tsx`: new nav + footer.
4. `landing-page.tsx` rewritten; hero demo is a small client component.
5. `/use-cases/` index, `use-case-page.tsx` restyle, `/integrations/` page.
6. Sitemap gets the two new routes.

## Files

- new: `site/src/components/marketing/site.css`, `hero-demo.tsx`,
  `site/src/app/use-cases/page.tsx`, `site/src/app/integrations/page.tsx`
- changed: `layout.tsx`, `sitemap.ts`, `landing-page.tsx`, `site-chrome.tsx`,
  `use-case-page.tsx`
- deleted: `landing.css`, `use-case-cards.tsx`
