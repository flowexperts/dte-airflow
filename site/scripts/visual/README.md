# Visual checks for the marketing landing page

Two Playwright scripts. `playwright` and `sharp` are dev dependencies; neither
script is wired into `pnpm build` or CI. One-time browser download:

```bash
cd site
npx playwright install chromium
```

> **Deploy note.** The `playwright` npm package downloads a browser in its
> postinstall hook, so a Cloudflare Pages build that installs dev dependencies
> pays for it. If build times jump, set `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` in
> the Pages environment, or install with `--prod`.

## `responsive-sweep.mjs`

```bash
node scripts/visual/responsive-sweep.mjs http://localhost:3000
```

Walks 320 → 1440px and reports horizontal overflow, page height, iframe count,
which layout branch is live (hero viz / Cal panel vs mobile CTA), and section
order.

**Why it exists:** `.mkt-root` sets `overflow-x: hidden`, so an element wider
than the viewport is silently *clipped* rather than producing a scrollbar. The
page looked fine on `main` at 360px while the entire hero column was rendering
410px wide and losing its right edge. Eyeballing cannot catch this; comparing
`scrollWidth` against the viewport can.

## `desktop-no-regression.mjs`

```bash
# dev server on the baseline branch :3178, candidate branch :3177
node scripts/visual/desktop-no-regression.mjs http://localhost:3178 http://localhost:3177
```

Full-page pixel diff at 1024/1280/1366/1440/1600/1920. `0 px` at every width is
the proof that mobile-only work left desktop untouched.

**Freeze the page first — the script does this for you.** Three things on this
page change over time and will otherwise swamp the signal with noise:

- the run-status pill cycles `pending → running → ok` every 2.4s
- the active-step highlight walks the hero viz every 0.9s
- the demo `<video>` animates *and* changes total page height as it loads

Before freezing these, a diff of the identical page against itself scored ~400
differing pixels, and one run of a genuinely-identical layout scored 13,499. Any
non-zero result from this script should be located (which rows differ, which
section owns them) before it's believed.
