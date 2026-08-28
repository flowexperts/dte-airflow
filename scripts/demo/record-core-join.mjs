#!/usr/bin/env node
/**
 * Flagship demo — a real multi-source pipeline against a real database.
 *
 * The story: an order system and a CRM (two schemas in the demo warehouse),
 * four joins, derived columns, a case band, then Auto-map onto a published
 * mart whose column names do not match — and a run over ~28k rows.
 *
 * Off-camera: re-seed via scripts/demo/seed-demo.py, then DELETE the select
 * step from the seeded pipeline. That deletion is the whole point. With the
 * select step in place the pipeline's output columns are already the mart's
 * column names, so Auto-map reports "11 of 13, all 100% exact" — a wall of
 * green that demonstrates nothing. Without it, Auto-map sees the raw joined
 * columns and returns 6 exact + 5 llm + 2 unmapped, which is a decision the
 * viewer watches someone make.
 *
 *   docker compose up -d --build
 *   ./scripts/demo/verify.sh          # do not skip this
 *   cd scripts/demo && node record-core-join.mjs
 *   ./encode.sh 'out/webm/core-join/*.webm' out/demo-core-join
 */

import {
  BASE_URL, DWELL, dwell, log, caption, say, apiLogin, api,
  startRecording, finishRecording, hoverPreview, showPreviewTab, showTab,
  runAutoMap, runPipeline,
} from "./lib.mjs";

const OUT_DIR = "out/webm/core-join";
const EMAIL = process.env.DTE_EMAIL ?? "demo@example.com";
const PASSWORD = process.env.DTE_PASSWORD ?? "demopass1234";
const PIPELINE_ID = "demo_order_facts_pipeline";

/** Strip the select step so Auto-map has something real to do. */
async function stripSelectStep(A) {
  const r = await A.get(`/api/pipelines/${PIPELINE_ID}`);
  if (r.status() !== 200) {
    throw new Error(
      `pipeline ${PIPELINE_ID} not found — run scripts/demo/seed-demo.py first`,
    );
  }
  const pipe = await r.json();
  const before = pipe.steps.length;
  pipe.steps = pipe.steps.filter((s) => s.op !== "select");
  if (pipe.steps.length === before) {
    log("no select step to strip (already stripped)");
    return;
  }
  const put = await A.put(`/api/pipelines/${PIPELINE_ID}`, pipe);
  if (put.status() >= 400) throw new Error(`strip select: ${await put.text()}`);
  log(`stripped select step (${before} -> ${pipe.steps.length})`);
}

async function main() {
  const { req, token } = await apiLogin(EMAIL, PASSWORD);
  const A = api(req, token);
  await stripSelectStep(A);

  const rec = await startRecording(OUT_DIR, token);
  const { page } = rec;

  try {
    // ── 1. The two systems ────────────────────────────────────────────────
    log("open pipeline canvas");
    await page.goto(`${BASE_URL}/pipelines/${PIPELINE_ID}`);
    await page.getByRole("button", { name: /Auto-map/i }).first()
      .waitFor({ timeout: 30_000 });
    await dwell(DWELL.md);

    await say(
      page,
      "Order facts — built from two systems: the order database and the CRM.",
      DWELL.read,
    );

    await caption(page, "Five tables across two sources. Schemas read live from Postgres.");
    for (const label of ["Order system", "CRM"]) {
      await page.getByRole("button", { name: label, exact: true }).first()
        .scrollIntoViewIfNeeded().catch(() => {});
      await dwell(DWELL.md);
    }
    await say(
      page,
      "orders, order_items, products from one — customers, regions from the other.",
      DWELL.read,
    );

    // ── 2. The joins ──────────────────────────────────────────────────────
    await caption(page, "Four joins. Each one names the table the next step reads.");
    for (const outputId of ["oi", "oip", "oipc"]) {
      const el = page.getByRole("button", { name: outputId, exact: true }).first();
      await el.scrollIntoViewIfNeeded().catch(() => {});
      await el.hover().catch(() => {});
      await dwell(DWELL.md);
    }
    await say(
      page,
      "orders ⨝ items ⨝ products ⨝ customers ⨝ regions — all pushed down into Postgres.",
      DWELL.read,
    );

    // ── 3. Derived columns + dialect readback ─────────────────────────────
    await caption(page, "Derived columns: line total, and the amount after discount.");
    const expr = page.getByText(/qty \* unit_price/).first();
    await expr.scrollIntoViewIfNeeded().catch(() => {});
    await expr.hover().catch(() => {});
    await dwell(DWELL.lg);
    await say(
      page,
      "The target is Postgres, so DTE shows the SQL Postgres will actually receive.",
      DWELL.read,
    );

    await caption(page, "And a case step bands every line into small / medium / large.");
    const band = page.getByText(/order_size/).first();
    await band.scrollIntoViewIfNeeded().catch(() => {});
    await dwell(DWELL.lg);

    // ── 4. Live preview + compiled SQL ────────────────────────────────────
    await hoverPreview(page);
    await say(page, "Live preview — real rows, refreshed as the spec changes.", DWELL.read);

    await caption(page, "Same pipeline, as the query the database runs.");
    await showPreviewTab(page, "SQL");
    await dwell(DWELL.xl);
    await say(page, "Four joins, one pushed-down query. No data left Postgres to be joined.", DWELL.read);
    await showPreviewTab(page, "Data");

    // ── 5. Auto-map: the beat ─────────────────────────────────────────────
    await say(
      page,
      "The mart it writes to uses different column names. That is the normal case.",
      DWELL.read,
    );
    await caption(page, "Auto-map reads the destination schema and proposes the mapping.");
    await runAutoMap(page, { acceptLowConfidence: true });
    await say(
      page,
      "Six matched by name outright. Five the model reasoned out — you approve those.",
      DWELL.read,
    );
    await say(
      page,
      "Two it could not map, and says so rather than guessing.",
      DWELL.read,
    );

    await caption(page, "It lands as one ordinary select step — the alias does the rename.");
    await dwell(DWELL.lg);

    await page.getByRole("button", { name: /^save$/i }).first().click();
    await dwell(DWELL.md);

    // ── 6. Run it ─────────────────────────────────────────────────────────
    await say(page, "Run it. The date is a trigger-time input, not a hardcoded filter.", DWELL.read);
    await runPipeline(page, { min_order_date: "2024-01-01" });
    await say(page, "Twenty-seven thousand rows, written straight into the warehouse.", DWELL.read);

    await caption(page, "Every run keeps its timeline and the exact SQL it ran.");
    await showTab(page, "Runs");
    await dwell(DWELL.xl);

    await say(
      page,
      "Two databases, four joins, a schema that did not match — and it is reproducible.",
      DWELL.read,
    );
    await caption(page, "");
  } catch (err) {
    log(`error: ${err.message}`);
    throw err;
  } finally {
    await finishRecording(rec, OUT_DIR);
    // Put the select step back so the next recording and verify.sh start
    // from the seeded state.
    await A.get(`/api/pipelines/${PIPELINE_ID}`);
    log("re-seed before the next run: python3 ../../scripts/demo/seed-demo.py");
  }
}

main().catch((err) => { console.error(err); process.exit(1); });
