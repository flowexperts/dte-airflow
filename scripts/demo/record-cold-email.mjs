#!/usr/bin/env node
/**
 * The 90-second cut — the asset you paste into a cold email.
 *
 * marketing-plans/002 §3 specifies this exactly: "a 90-second Loom of their
 * data going in messy and coming out clean, in their column names". So it is
 * that and nothing else — no tour, no feature list, no narration beats that
 * exist to explain the product rather than show it.
 *
 * Same seeded world as record-core-join.mjs, run at roughly triple speed and
 * with the build skipped: the pipeline already exists, the viewer joins at
 * the moment the column names do not line up.
 *
 * Hard budget: 95 seconds. If it grows past that, cut a beat rather than
 * speeding the remaining ones up further — past ~2x the captions stop being
 * readable and the whole thing reads as a blur.
 *
 *   ./scripts/demo/verify.sh
 *   cd scripts/demo && node record-cold-email.mjs
 *   ./encode.sh 'out/webm/cold-email/*.webm' out/demo-cold-email-90s
 */

import {
  BASE_URL, DWELL, TIMING, dwell, log, caption, say, apiLogin, api,
  startRecording, finishRecording, hoverPreview, showPreviewTab,
  runAutoMap, runPipeline,
} from "./lib.mjs";

// Tighter than the walkthroughs. Captions are shorter here to match.
Object.assign(DWELL, { xs: 300, sm: 500, md: 800, lg: 1200, xl: 1600, read: 2600 });
TIMING.slowMo = 0;
TIMING.typeDelay = 25;
TIMING.clickPause = 150;

const OUT_DIR = "out/webm/cold-email";
const EMAIL = process.env.DTE_EMAIL ?? "demo@example.com";
const PASSWORD = process.env.DTE_PASSWORD ?? "demopass1234";
const PIPELINE_ID = "demo_order_facts_pipeline";

/** Same strip as record-core-join.mjs — without it Auto-map has nothing to do. */
async function stripSelectStep(A) {
  const r = await A.get(`/api/pipelines/${PIPELINE_ID}`);
  if (r.status() !== 200) {
    throw new Error(`${PIPELINE_ID} not found — run scripts/demo/seed-demo.py first`);
  }
  const pipe = await r.json();
  const before = pipe.steps.length;
  pipe.steps = pipe.steps.filter((s) => s.op !== "select");
  if (pipe.steps.length === before) return;
  const put = await A.put(`/api/pipelines/${PIPELINE_ID}`, pipe);
  if (put.status() >= 400) throw new Error(`strip select: ${await put.text()}`);
  log(`stripped select step (${before} -> ${pipe.steps.length})`);
}

async function main() {
  const { req, token } = await apiLogin(EMAIL, PASSWORD);
  const A = api(req, token);
  await stripSelectStep(A);

  const started = Date.now();
  const rec = await startRecording(OUT_DIR, token);
  const { page } = rec;

  try {
    await page.goto(`${BASE_URL}/pipelines/${PIPELINE_ID}`);
    await page.getByRole("button", { name: /Auto-map/i }).first()
      .waitFor({ timeout: 30_000 });
    await dwell(DWELL.md);

    await say(page, "Your orders. Two systems, five tables.", DWELL.read);

    await hoverPreview(page);
    await say(page, "Joined, filtered, totalled — 28,000 rows.", DWELL.read);

    await showPreviewTab(page, "SQL");
    await say(page, "One query, pushed down into your database.", DWELL.read);
    await showPreviewTab(page, "Data");

    await say(page, "Your warehouse uses different column names.", DWELL.read);
    await runAutoMap(page, { acceptLowConfidence: true });
    await say(page, "Mapped. Six by name, five by model, two it won't guess.", DWELL.read);

    await page.getByRole("button", { name: /^save$/i }).first().click();
    await dwell(DWELL.md);

    await runPipeline(page, { min_order_date: "2024-01-01" });
    await say(page, "Written to your warehouse. In your column names.", DWELL.read);
    await caption(page, "");
  } catch (err) {
    log(`error: ${err.message}`);
    throw err;
  } finally {
    await finishRecording(rec, OUT_DIR);
    const secs = Math.round((Date.now() - started) / 1000);
    log(`wall clock: ${secs}s${secs > 95 ? "  ← over the 95s budget, cut a beat" : ""}`);
  }
}

main().catch((err) => { console.error(err); process.exit(1); });
