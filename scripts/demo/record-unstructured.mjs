#!/usr/bin/env node
/**
 * Unstructured demo — PDFs into the warehouse, then reconciled against it.
 *
 * Opens cold on the provenance inspector (marketing-plans/009 §3: "fifteen
 * seconds, and the only moment no competitor can reproduce"), then shows the
 * build, then — the part that matters — does NOT stop at extracted text.
 * marketing-plans/009 §8.3: "a demo that stops at extracted text has conceded
 * the comparison." So it continues into pipeline C, which joins the extracted
 * invoices against the vendor bills already in Postgres and surfaces the two
 * that disagree.
 *
 * Those two disagreements are real, not staged: the eval corpus ships two
 * PDFs per invoice number and the INV-1004 / INV-1005 pairs carry different
 * totals ($340.00 vs $412.75, $2,050.00 vs $12,000.00).
 *
 * Needs ANTHROPIC_API_KEY in .env — the structure step is a real model call.
 *
 *   ./scripts/demo/verify.sh
 *   cd scripts/demo && node record-unstructured.mjs
 *   ./encode.sh 'out/webm/unstructured/*.webm' out/demo-unstructured
 */

import {
  BASE_URL, DWELL, dwell, log, caption, say, apiLogin, api,
  startRecording, finishRecording, hoverPreview, showTab, runPipeline,
} from "./lib.mjs";

const OUT_DIR = "out/webm/unstructured";
const EMAIL = process.env.DTE_EMAIL ?? "demo@example.com";
const PASSWORD = process.env.DTE_PASSWORD ?? "demopass1234";
const EXTRACT_ID = "demo_invoice_extract";
const RECON_ID = "demo_invoice_recon";

/**
 * Make sure both pipelines have run at least once, off camera. The cold-open
 * needs extracted rows to inspect, and re-extracting ten PDFs live would put
 * a model call on the critical path of the first fifteen seconds.
 */
async function ensureRun(A, id, body = {}) {
  const runs = await (await A.get(`/api/pipelines/${id}/runs`)).json().catch(() => []);
  const done = (Array.isArray(runs) ? runs : runs.items ?? [])
    .some((r) => r.status === "completed");
  if (done) { log(`${id}: already has a completed run`); return; }
  log(`${id}: triggering (off camera)`);
  const r = await A.post(`/api/pipelines/${id}/trigger`, body);
  const { run_id } = await r.json();
  for (let i = 0; i < 120; i++) {
    const run = await (await A.get(`/api/runs/${run_id}`)).json();
    if (run.status === "completed") return;
    if (run.status === "failed") throw new Error(`${id} failed: ${run.error}`);
    await dwell(2000);
  }
  throw new Error(`${id}: run never finished`);
}

async function main() {
  const { req, token } = await apiLogin(EMAIL, PASSWORD);
  const A = api(req, token);
  await ensureRun(A, EXTRACT_ID);
  await ensureRun(A, RECON_ID);

  const rec = await startRecording(OUT_DIR, token);
  const { page } = rec;

  try {
    // ── 1. Cold open: provenance ──────────────────────────────────────────
    log("cold open: extracted rows");
    await page.goto(`${BASE_URL}/pipelines/${EXTRACT_ID}`);
    await page.getByRole("button", { name: /▶\s*Run/i }).first()
      .waitFor({ timeout: 30_000 });
    await dwell(DWELL.md);

    await hoverPreview(page);
    await say(page, "These numbers came out of ten PDF invoices.", DWELL.read);

    // The inspect gutter only renders for document-backed rows.
    const inspect = page.locator('button[aria-label*="nspect"], button[title*="nspect"]').first();
    if (!(await inspect.isVisible().catch(() => false))) {
      throw new Error(
        "no inspect affordance on any row — the provenance cold-open is the " +
        "point of this recording, so this is a hard failure, not a skip",
      );
    }

    await caption(page, "Every one of them can point at where it came from.");
    await inspect.click();

    // Wait for the page to actually paint, and refuse to film the error
    // panel. pdf.js renders into a <canvas>; a dwell alone would happily
    // record "Could not open the document" under a caption claiming the
    // opposite, which is exactly what shipped once already.
    const failed = page.getByText(/could not open the document/i).first();
    const canvas = page.locator("canvas").first();
    await Promise.race([
      canvas.waitFor({ state: "visible", timeout: 30_000 }),
      failed.waitFor({ state: "visible", timeout: 30_000 }),
    ]);
    if (await failed.isVisible().catch(() => false)) {
      const detail = await page.locator("text=/is not a function|ERROR/i").first()
        .innerText().catch(() => "");
      throw new Error(
        `document inspector failed to render (${detail.trim()}). If this is ` +
        "\"n.toHex is not a function\", the recording browser is Playwright's " +
        "bundled Chromium 130 rather than real Chrome — see launchBrowser() " +
        "in lib.mjs.",
      );
    }
    // Painted, not merely present: a blank canvas is still a bad shot.
    await page.waitForFunction(() => {
      const c = document.querySelector("canvas");
      return c && c.width > 50 && c.height > 50;
    }, { timeout: 20_000 }).catch(() => {});
    await dwell(DWELL.xl);
    await say(page, "The source page, with the exact words the value was read from.", DWELL.read);
    await page.keyboard.press("Escape").catch(() => {});
    await dwell(DWELL.sm);

    // ── 2. How it was built ───────────────────────────────────────────────
    await say(page, "Two steps built that. Extract the text, then declare the shape.", DWELL.read);

    await caption(page, "Extract: the PDFs, read page by page.");
    const extractRow = page.getByText(/extract/i).first();
    await extractRow.scrollIntoViewIfNeeded().catch(() => {});
    await dwell(DWELL.lg);

    await caption(page, "Structure: the columns you want, described in plain language.");
    const structRow = page.getByText(/structure/i).first();
    await structRow.scrollIntoViewIfNeeded().catch(() => {});
    await dwell(DWELL.xl);
    await say(
      page,
      "From here on it is ordinary tabular data — every other step just works on it.",
      DWELL.read,
    );

    // ── 3. It lands in the warehouse ──────────────────────────────────────
    await caption(page, "And it writes to Postgres, not to a file.");
    await dwell(DWELL.lg);
    await say(page, "staging.invoice_lines — a real table, in the real warehouse.", DWELL.read);

    // ── 4. The part that matters: reconcile ───────────────────────────────
    log("open reconciliation pipeline");
    await page.goto(`${BASE_URL}/pipelines/${RECON_ID}`);
    await page.getByRole("button", { name: /▶\s*Run/i }).first()
      .waitFor({ timeout: 30_000 });
    await dwell(DWELL.md);

    await say(
      page,
      "Which means the next pipeline can join it against what was already there.",
      DWELL.read,
    );
    await caption(page, "Extracted invoices ⨝ the vendor bills in the order system.");
    await dwell(DWELL.lg);

    await say(page, "Run it, and ask where the two disagree.", DWELL.read);
    await runPipeline(page, {});

    await hoverPreview(page);
    await say(
      page,
      "Two invoices do not match the bill. Found by joining a PDF to a database.",
      DWELL.read,
    );

    await showTab(page, "Runs");
    await dwell(DWELL.lg);
    await say(
      page,
      "Extraction is the easy half. Owning what happens next is the product.",
      DWELL.read,
    );
    await caption(page, "");
  } catch (err) {
    log(`error: ${err.message}`);
    throw err;
  } finally {
    await finishRecording(rec, OUT_DIR);
  }
}

main().catch((err) => { console.error(err); process.exit(1); });
