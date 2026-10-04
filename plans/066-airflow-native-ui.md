# Plan 066 — DTE UI as a native Airflow `react_apps` plugin

## Context
DTE's UI is a Next.js 16 static export. It's served at `/dte/ui` and shown in Airflow through `external_views`, which is an iframe (plan 065). As a result it has its own fonts (Outfit / Space Mono / Cormorant), its own warm palette and its own light/dark toggle, so it doesn't look like Airflow. Goal: DTE renders inside Airflow's page and inherits Airflow's theme, fonts and colour mode as they're configured.

What I checked in the running Airflow 3.1.8:
- **`react_apps` is supported.** Each entry has `bundle_url`, `name`, `destination` and `url_route`. The UI `import()`s the bundle, then renders `globalThis[name] ?? globalThis.AirflowPlugin` inside its own layout. The route is `plugin/:page/*`, so sub-paths under `/plugin/dte/...` reach the plugin.
- **Airflow shares its runtime libraries.** It sets `globalThis.React`, `ReactDOM`, `ReactJSXRuntime` and `ReactRouterDOM`. Chakra is not shared.
- **The theme is Chakra v3 CSS variables on `<html>`.** Colours are `--chakra-colors-*` and fonts are `--chakra-fonts-{body,heading,mono}` (Inter/system stack, SFMono stack). Dark mode is `html.dark` and the colour variables switch with it. So a component in Airflow's DOM that styles itself with those variables follows the theme with no JS. That includes a future `[api] theme` (3.2+), which only changes the same variables.
- It's the same origin, so `apiFetch` (`credentials: "same-origin"`, base `/dte`) and auth stay as they are.

Size of the migration: 21 App Router pages. 42 `next/link` / `next/navigation` imports and one `next/font`. Pages already route by query string (`detail?id=`), so there are no dynamic segments to convert.

## Architecture change
- Next.js is replaced by a **Vite library build** (UMD, `name: "AirflowPlugin"`, default export). `react`, `react-dom`, `react/jsx-runtime` and `react-router-dom` are marked external and mapped to Airflow's globals. The output is one `dte.umd.js`, still served by the existing `_UiFiles` mount at `/dte/ui` (`backend/dte/api/main.py:73`).
- One root component, `src/plugin.tsx`. It renders `<div className="dte-root">` → `SwrProvider` → `Toaster` → `AppSidebar` + `<Routes>`, using Airflow's own router with paths relative to `/plugin/:page/*`. The `page` param picks the landing section (`dte`→pipelines, `dte-sources`→sources, and so on). All four menu entries share the bundle.
- **CSS is scoped:**
  - Tailwind v4 without preflight: import the `theme` and `utilities` layers only.
  - Tokens are defined on `.dte-root` as `var(--chakra-colors-…)` and fonts as `var(--chakra-fonts-body|mono)`, so there are no `html, body` rules.
  - The CSS is imported with `?inline` and injected once as a `<style>` on first mount, so no new dependency is needed.
  - The chart palette (plan 064, validated) stays as-is.

## Tasks (worktree `feature/airflow-native-ui`)
1. `plans/066-airflow-native-ui.md`: this plan.
2. **Build:** add `vite` + `@vitejs/plugin-react` + `@tailwindcss/vite`, and remove `next`, `eslint-config-next`, `@next/bundle-analyzer` and `next.config.ts`. Add `vite.config.ts` (lib mode, UMD, externals→globals, `@` alias, `publicDir` for the pdf worker). Scripts: `build` = `vite build`, `dev` = `vite build --watch`.
3. **Navigation shim `src/lib/nav.tsx`:** Next-shaped wrappers over `react-router-dom`: `Link` (`href`→`to`), `useRouter` (`push/replace/back`), `useSearchParams` (returns the params object), `usePathname`. Then codemod `from "next/link"|"next/navigation"` → `from "@/lib/nav"`. Links and pushes stay relative to the plugin base, so page code doesn't change.
4. **Routes:** move the 21 `src/app/(app)/**/page.tsx` files to `src/pages/`, keeping their bodies, and list them in one route table in `plugin.tsx`. Remove `app/layout.tsx` (fonts plus the iframe-bounce script), `app/page.tsx` and `app/error.tsx`. Airflow's plugin loader already catches load errors.
5. **Theme:**
   - Rewrite `globals.css` as `dte.css` under `.dte-root`, with tokens from Chakra vars: bg←`bg`, surface←`bg.panel`, surface-2←`bg.subtle`, hover←`bg.muted`, border←`border`, border-2←`border.emphasized`, text←`fg`, muted←`fg.muted`, subtle←`fg.subtle`, accent←`brand.solid`, green←`success.fg`, red←`danger.fg`, gold←`warning.fg`. Check the exact names against the live page before relying on them.
   - Delete `theme-provider.tsx` and `theme-toggle.tsx`, and remove the toggle from `ui/sidebar.tsx`. Replace the Cormorant wordmark font with the heading font.
   - Any `useTheme()` consumer (for example, chart colours) reads `document.documentElement.classList.contains("dark")` instead.
6. **Plugin:** in `backend/dte/airflow/plugin.py`, swap `external_views` for `react_apps` with the same four entries (`bundle_url="/dte/ui/dte.umd.js"`, same `url_route`s and `category="admin"`). Update the unit test that asserts the plugin shape.
7. **Image:** in `Dockerfile.airflow`, copy `/app/dist` instead of `/app/out`.
8. **E2E:** point Playwright at `/plugin/dte/...` instead of `/dte/ui/...`.
9. **Docs:** in `frontend/CLAUDE.md`, replace the Next.js sections (ports, App Router, Next 16 gotchas, server/client discipline) with the Vite/plugin model, the nav shim and scoped CSS. Delete `frontend/AGENTS.md`. Update the design-system note: tokens come from Airflow, and the fonts and toggle are gone.

Skipped:
- A Tailwind `prefix(dte)`. Utility-class collisions with Chakra's generated `css-*` classes are unlikely; add the prefix if a clash shows up.
- A standalone dev harness page. Develop against Airflow with `vite build --watch` and reload.

## Verification
- `cd frontend && pnpm typecheck && pnpm test && pnpm build`. The build produces `dist/dte.umd.js` with no bundled React (grep the bundle for `__SECRET_INTERNALS`/`react.production`: none).
- `cd backend && uv run pytest tests/unit -k plugin`.
- `docker compose up -d --build`, log in admin/admin, then use Claude-in-Chrome:
  - `/plugin/dte` renders DTE with no `<iframe>` in the DOM.
  - Text is Inter, and bg/fg/brand match Airflow's.
  - Airflow's light/dark toggle restyles DTE live.
  - Pipelines → detail → run, the builder and the Admin → DTE Sources/Destinations/Lookup tables all navigate, and the browser back button works.
  - Airflow's own pages look unchanged: no leaked reset or body styles.
  - Screenshot both colour modes.
- `pnpm test:e2e` passes against the compose stack.
