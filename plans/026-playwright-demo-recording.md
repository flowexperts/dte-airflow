# 026 — Playwright demo recording

## Context

The launch funnel needs a moving-picture asset. Currently the landing page (`frontend/src/components/marketing/landing-page.tsx`) and the README both *describe* the flow — a stranger evaluating DTE has to trust that description without seeing the product move. A 60–90 s clip that shows the empty canvas → mapped pipeline → run output collapse of DTE's pitch would go on the landing hero (MP4) and the GitHub README (GIF), and it's the single highest-leverage marketing artifact for OSS + book-a-call.

Loom is the obvious tool, but a Playwright-driven recording has two properties Loom doesn't: it re-runs deterministically when the UI changes (no re-recording the day after a headline tweak), and it can double as a visual smoke test. Downside: the cursor path and typing cadence look robotic. We accept that tradeoff for now — for the marketing hero we may later swap in a Loom with narration; the Playwright artifact is the always-current fallback and the primary asset in the README.

Scope of this plan: a single-purpose recording script that drives the **local dev stack** at `localhost:3000` and produces two encoded artifacts. Not a test suite, not a CI job, not an ephemeral-stack orchestrator.

## Approach

### 1. Location and shape

- New folder `scripts/demo/`.
- `scripts/demo/record.mjs` — the Playwright script (Node ESM, no build step).
- `scripts/demo/package.json` — pins `playwright` only.
- `scripts/demo/README.md` — one-page "how to regenerate the demo" instructions.
- `scripts/demo/out/` — untracked; add to `.gitignore`. Contains WebM (raw), MP4 (encoded), GIF (encoded), and a `frames/` scratch dir.

### 2. Preconditions the script assumes (not orchestrates)

- Local stack up on `localhost:3000` / `localhost:8001`.
- A fixture JSON already present inside the backend container. Reuse `backend/tests/scenarios/fixtures/orders.json` — it's tracked, mounted via `./backend`, and the compiler already knows how to read it via the `filesystem` source kind. **In-container path**: `/app/tests/scenarios/fixtures` (verify by checking the backend Dockerfile's `WORKDIR`). The demo source will point at this directory.
- No prior demo user in the DB. The script uses a timestamped email (`demo+<epoch>@dte.local`) so re-runs don't collide. If the run fails partway, subsequent runs still get a fresh user.

### 3. Flow the script performs (target: ~75 s of video)

```
1. goto /                          → landing page  (2 s dwell)
2. click "Open app" / navigate to /login
3. click "Sign up"                 → /register
4. fill email + password + name    → submit → auto-redirect to /pipelines
5. click "New source" or go to /sources → filesystem source editor
   - id: "demo_orders"
   - bucket_url: "/app/tests/scenarios/fixtures"
   - file_glob: "orders.json"
   - Save
6. Go to /pipelines → New pipeline
   - id: "demo_orders_pipeline", name: "Orders pipeline"
   - Pick source: demo_orders
   - Add step: filter, expr `amount > 50`
   - Add step: rename, `customer_id → cust_id`
   - Pick destination: inline-create json_file at /tmp/demo_output.json
   - Save
7. Preview panel loads → dwell 2 s
8. Trigger → poll to completion → land on /runs/{id}
9. Dwell on the MetricRow (rows written, elapsed) for 2 s
10. Optional: peek at /api/runs/{id}/output via the UI, dwell 2 s
```

Timing knobs live at the top of `record.mjs`:

```js
const DWELL = { short: 800, medium: 1600, long: 2400 };
const TYPE_DELAY = 40;  // ms per keystroke — deliberately slow for readability
```

Every action goes through `await page.locator(...).click()` etc. — no `sleep()` for readiness; only `dwell()` for narrative pacing. If the app is slow, Playwright waits; if the app is fast, `dwell()` still holds the frame long enough to read.

### 4. Recording setup

```js
const context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  recordVideo: { dir: "scripts/demo/out/webm", size: { width: 1280, height: 800 } },
  deviceScaleFactor: 2,   // Retina crispness
});
```

Headed mode with `slowMo: 40` for readable motion. `headless: false` — a real Chromium window pops open, which is fine on the dev laptop.

### 5. Encoding

After the script exits and Playwright finalises the WebM, run `scripts/demo/encode.sh`:

```bash
ffmpeg -i out/webm/*.webm -vcodec libx264 -crf 22 -preset slow \
       -movflags +faststart out/demo.mp4

ffmpeg -i out/demo.mp4 -vf "fps=15,scale=960:-1:flags=lanczos,split[s0][s1];
       [s0]palettegen[p];[s1][p]paletteuse" -loop 0 out/demo.gif
```

- MP4: 1280×800, `+faststart` so it streams on the landing page.
- GIF: 960 wide, 15 fps — small enough for GitHub's 10 MB README image limit.

### 6. Root `package.json` script (optional shortcut)

If a root `package.json` doesn't already exist, don't create one. Instead the demo README says:

```bash
cd scripts/demo && npm install && node record.mjs && ./encode.sh
```

### 7. Failure paths and re-run behaviour

- If `localhost:3000` isn't reachable, the script errors out on `page.goto` — good, that's the right failure mode.
- If any selector doesn't resolve within Playwright's default 30 s timeout, script fails. The demo is only useful if selectors are stable, so this doubles as a shallow smoke check.
- Every recording overwrites the previous `out/` contents. The script does *not* commit anything.

### 8. What we're not doing

- No ephemeral stack (compose up/down in the script).
- No CI wiring — this is a hand-run generator.
- No frame-level compositing (title cards, captions). If we want a titled hero video later, edit the MP4 in a real NLE.
- No accessibility of automated cursor gestures (hover-highlight, click ripple). Playwright doesn't render these.

## Critical files

**New**
- `scripts/demo/record.mjs` — Playwright driver.
- `scripts/demo/encode.sh` — ffmpeg pipeline.
- `scripts/demo/package.json` — pins playwright.
- `scripts/demo/README.md` — regeneration instructions.
- `.gitignore` — add `scripts/demo/out/` and `scripts/demo/node_modules/`.

**Modified** — none.

## Reuse

- Fixture: `backend/tests/scenarios/fixtures/orders.json` (already tracked, hand-crafted, deterministic).
- No selectors extracted from the scenario suite — those tests use HTTP, not the browser.
- Selector strategy: prefer `getByRole` and `getByLabel` over CSS/xpath; add `data-testid` in `frontend/` **only if** an existing element has no stable accessible name (do this on a follow-up branch, not in this plan).

## Verification

```bash
# Preconditions
docker compose up -d --build           # dev stack must be running
curl -sf http://localhost:8001/healthz  # backend up
curl -sf http://localhost:3000         # frontend up

# Record
cd scripts/demo
npm install
node record.mjs                        # opens Chromium, runs the flow, exits
./encode.sh                            # produces out/demo.mp4 + out/demo.gif

# Sanity-check the artifacts
open out/demo.mp4                      # macOS QuickTime
open out/demo.gif                      # macOS Preview
du -h out/demo.mp4 out/demo.gif        # MP4 <5 MB, GIF <8 MB target
```

Success = both artifacts play the full flow end-to-end, no black frames, no visible error toasts, run status ends on "completed", and MetricRow shows a non-zero `rows_written`.
