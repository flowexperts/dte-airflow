# Plan 033 — Frontend performance pass

Covers P2 #26 from `plans/027-p0-p4-status-ladder.md`.

## Baseline (to measure before touching anything)

Steps for the first PR:

1. `cd frontend && pnpm build` — record the top-line first-load JS per route from Next's output.
2. `cd frontend && ANALYZE=true pnpm build` — after wiring the analyzer (below), attach the bundle-treemap screenshot to the PR.
3. Lighthouse against the docker-compose stack for `/pipelines`, `/pipelines/[id]`, `/runs/[id]`, `/preview`. Record LCP, TTI, TBT.

## Bundle analyzer

- Add `@next/bundle-analyzer` to `frontend/devDependencies`.
- Wire in `next.config.ts`:

  ```ts
  import bundleAnalyzer from "@next/bundle-analyzer";
  const withAnalyzer = bundleAnalyzer({ enabled: process.env.ANALYZE === "true" });
  export default withAnalyzer({ /* existing config */ });
  ```

- Add `"analyze": "ANALYZE=true next build"` under `frontend/package.json` scripts.

Report the top 5 chunk contributors in the PR. Likely suspects: `ibis` types (unlikely, they're purely type-level), `date-fns` (not used), heavy icon sets, the three Google fonts.

## Route audit — retire blanket `force-dynamic`

Grep target: `export const dynamic = "force-dynamic"` across `frontend/src/app/**/*.tsx`.

Per-route decision matrix:

| Route | Today | Target | Why |
| - | - | - | - |
| `/pipelines` (list) | force-dynamic | **ISR, revalidate: 30** | List changes rarely between edits; SWR client-side revalidates for freshness. |
| `/pipelines/[id]` | force-dynamic | **ISR, revalidate: 30** | Same shape. |
| `/pipelines/[id]/edit` | force-dynamic | **dynamic** (stays) | Editing state must reflect latest saved values. |
| `/pipelines/new` | force-dynamic | **static** | No server data. |
| `/runs/[id]` | force-dynamic | **dynamic** (stays) | Polls status; client SWR is authoritative. |
| `/sources` | force-dynamic | **ISR, revalidate: 60** | |
| `/destinations` | force-dynamic | **ISR, revalidate: 60** | |
| `/connections` | force-dynamic | **dynamic** (stays) | Contains credential-reveal endpoints; server must re-authorize each hit. |
| `/preview` | force-dynamic | **static** | Component gallery — no API calls. |

Rule of thumb: **`dynamic` for anything auth-gated whose payload varies per user**; **`ISR` for lists whose staleness is measured in seconds**; **`static` for pure-UI pages**.

Note: SWR still hits the API client-side. ISR only affects the *initial HTML shell* served by the server.

## Font strategy

Three Google fonts loaded in `layout.tsx`: Outfit (5 weights), Space Mono (2 weights), Cormorant Garamond (italic + normal @ 500). Cormorant is used exclusively for the `dt·e` wordmark — one instance.

- Verify `next/font` handles preload — should, but check `<link rel="preload">` in prod HTML.
- Drop Cormorant to italic-only (its only use) — halves that font's weight.
- Consider dropping Outfit 300 if unused; grep for `font-weight: 300` and `font-light`.

Expected savings: 40-60 KB on first paint.

## Prefetching audit

Next 16 prefetches all `<Link>`s in viewport by default. Confirm we're not prefetching heavy edit routes from the pipeline list — mark those `<Link prefetch={false}>` if so.

## Success metric

- First-load JS < **200 KB** per route (currently unknown; measure in baseline PR).
- LCP < **2.5 s** on the pipelines list.
- No regressions in Lighthouse Performance vs. baseline.

## Task list

- `feature/fe-bundle-analyzer` — analyzer + baseline PR + captured screenshot.
- `feature/fe-route-audit` — route-by-route retire of `force-dynamic`.
- `feature/fe-font-audit` — drop unused font weights, verify preload.

## Non-goals

- Migrating to a different bundler (Turbopack already in use).
- Server-side data prefetching / RSC-heavy refactor. SWR is fine.
- Image optimisation (no product images).
