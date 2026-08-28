#!/usr/bin/env node
/**
 * The hero cut — a pipeline built from nothing, on camera, in ~90 seconds.
 *
 * The other three recordings all open a pipeline that already exists and
 * explain it. This one starts on an empty /pipelines/new and ends with rows
 * in Postgres: name it, pick two sources and three tables, join them, derive
 * a column, Auto-map onto a destination whose names don't match, run it.
 *
 * Writes to analytics.customer_orders rather than the 13-column
 * analytics.order_facts mart: this builds a three-table join, and mapping
 * that onto the big mart would leave most of the Auto-map dialog unmapped,
 * which reads as failure rather than as honesty.
 *
 *   ./scripts/demo/verify.sh
 *   cd scripts/demo && node record-build.mjs
 *   ./encode-web.sh 'out/webm/build/*.webm' out/web/dte-demo 8
 */

import {
  BASE_URL, DWELL, TIMING, dwell, log, caption, say, apiLogin, api,
  startRecording, finishRecording, inputByLabel, typeInto, pickDropdown,
  pickFieldTree, hoverPreview, runAutoMap, runPipeline, humanClick, look,
  openAndPick,
} from "./lib.mjs";

// Paced for a person, not a script. Every click glides to its target and
// rests before pressing, and every dropdown stays open long enough to read —
// see humanClick/openAndPick in lib.mjs. slowMo stays 0 because the pauses
// are placed deliberately rather than smeared across every action.
Object.assign(DWELL, { xs: 400, sm: 700, md: 1100, lg: 1700, xl: 2300, read: 3200 });
TIMING.slowMo = 0;
TIMING.typeDelay = 55;
TIMING.clickPause = 320;

const OUT_DIR = "out/webm/build";
const EMAIL = process.env.DTE_EMAIL ?? "demo@example.com";
const PASSWORD = process.env.DTE_PASSWORD ?? "demopass1234";
const PIPELINE_NAME = "Customer orders";

/** Pipeline names are unique per workspace, so clear the last take's. */
async function deleteByName(A, name) {
  const r = await A.get("/api/pipelines");
  if (r.status() !== 200) return;
  const body = await r.json();
  const items = Array.isArray(body) ? body : body.items ?? [];
  for (const p of items.filter((p) => p.name === name)) {
    await A.del(`/api/pipelines/${p.id}`);
    log(`deleted stale pipeline ${p.id}`);
  }
}

/** Pick a source, then choose the table on the row it just added. */
async function addSourceTable(page, sourceName, tableName) {
  await openAndPick(
    page,
    page.getByRole("button", { name: /— pick a source —/ }).first(),
    new RegExp(`^${sourceName}`),
  );
  await pickTable(page, tableName);
}

async function pickTable(page, tableName) {
  await openAndPick(
    page,
    page.getByRole("button", { name: /— pick a table —/ }).last(),
    new RegExp(`^${tableName}$`),
  );
  // The alias auto-fills from the table name, so there is nothing to type —
  // but rest on it for a beat so the viewer sees that it did.
  await look(page, page.locator('input[placeholder]').last(), DWELL.md);
}

/** Add a join, filling the editor that was just appended (hence "last"). */
async function addJoin(page, { left, right, on, outputId }) {
  await humanClick(page, page.getByRole("button", { name: /add step/i }).first());
  // Hold on the op palette — twelve step types is the product, and it is on
  // screen for exactly as long as this pause.
  await dwell(DWELL.xl);
  await humanClick(page, page.getByRole("button", { name: /^Join$/i }).first());
  await dwell(DWELL.md);

  await pickDropdown(page, "Left", new RegExp(`^${left}$`), "last");
  await pickDropdown(page, "Right", new RegExp(`^${right}$`), "last");

  const onWrap = page.locator('label:text-is("On")').last().locator("xpath=..");
  await pickFieldTree(onWrap, page, "user_id", on);

  await typeInto(inputByLabel(page, "Output id", "last"), outputId, page);
  await dwell(DWELL.md);
}

async function main() {
  const { req, token } = await apiLogin(EMAIL, PASSWORD);
  const A = api(req, token);
  await deleteByName(A, PIPELINE_NAME);

  const rec = await startRecording(OUT_DIR, token);
  const { page } = rec;

  try {
    log("open /pipelines/new");
    await page.goto(`${BASE_URL}/pipelines/new`);
    await page.getByRole("button", { name: /— pick a source —/ }).first()
      .waitFor({ timeout: 30_000 });
    await dwell(DWELL.sm);

    await say(page, "A new pipeline, from nothing.", DWELL.read);
    await typeInto(inputByLabel(page, "Name"), PIPELINE_NAME, page);
    await dwell(DWELL.md);

    // ── sources ───────────────────────────────────────────────────────────
    await caption(page, "Two systems. Three tables.");
    await addSourceTable(page, "Order system", "orders");

    await humanClick(
      page,
      page.getByRole("button", { name: /\+ Add table from Order system/ }).first(),
    );
    await pickTable(page, "order_items");

    await addSourceTable(page, "CRM", "customers");
    await say(page, "Schemas read straight out of Postgres.", DWELL.read);

    // ── destination ───────────────────────────────────────────────────────
    await caption(page, "And where it lands.");
    await openAndPick(
      page,
      page.getByRole("button", { name: /— pick a destination —/ }).first(),
      /customer_orders/,
    );

    // ── joins ─────────────────────────────────────────────────────────────
    await caption(page, "Join the orders to their line items…");
    await addJoin(page, { left: "orders", right: "order_items", on: "order_id", outputId: "oi" });

    await caption(page, "…and that to the customer.");
    await addJoin(page, { left: "oi", right: "customers", on: "customer_id", outputId: "joined" });

    // ── derived column ────────────────────────────────────────────────────
    await caption(page, "One derived column.");
    await humanClick(page, page.getByRole("button", { name: /add step/i }).first());
    await dwell(DWELL.xl);
    await humanClick(page, page.getByRole("button", { name: /^Map · expression$/i }).first());
    await dwell(DWELL.md);
    await typeInto(inputByLabel(page, "Output field", "last"), "line_total", page);
    // Not inputByLabel("Expression"): commit 42ca94d moved the expression
    // builder trigger onto the label row, so the label's text is literally
    // "Expression+ build one" and an exact match finds nothing. The textarea
    // placeholder is the stable handle.
    await typeInto(page.locator("textarea").last(), "qty * unit_price", page);
    await dwell(DWELL.xl);

    await hoverPreview(page);
    await say(page, "Live preview, the whole way down.", DWELL.read);

    // ── automap ───────────────────────────────────────────────────────────
    await say(page, "The target's column names don't match. They rarely do.", DWELL.read);
    await runAutoMap(page, { acceptLowConfidence: true });
    await say(page, "Matched by name where it can, by model where it can't.", DWELL.read);

    // ── save + run ────────────────────────────────────────────────────────
    await caption(page, "Save it.");
    await humanClick(page, page.getByRole("button", { name: /save pipeline/i }));
    await page.waitForURL(/\/pipelines\/[^/]+$/, { timeout: 20_000 });
    await dwell(DWELL.md);

    await runPipeline(page, {});
    await say(page, "Built and running, in ninety seconds.", DWELL.read);
    await caption(page, "");
  } catch (err) {
    log(`error: ${err.message}`);
    throw err;
  } finally {
    await finishRecording(rec, OUT_DIR);
  }
}

main().catch((err) => { console.error(err); process.exit(1); });
