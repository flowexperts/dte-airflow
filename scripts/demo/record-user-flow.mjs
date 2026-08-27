#!/usr/bin/env node
/**
 * User-facing DTE demo — records the pipeline-authoring flow with on-screen
 * captions and a deliberate cadence.
 *
 * Off-camera (via API): ensure a `local-fs` connection, an `orders-json`
 * source, and an `orders-output` destination exist. Connection is tested;
 * source schema is fetched to confirm end-to-end reachability. Any stale
 * `orders-demo` pipeline is deleted so the recording starts from a clean
 * history.
 *
 * On-camera: browser opens on /pipelines/new. Viewer sees the pipeline
 * built (source + destination pick, then Filter → Sort → Aggregate added
 * one step at a time with the preview panel refreshing in between),
 * triggered to completion, and the history panel diffed against a prior
 * revision.
 *
 *   docker compose up -d --build     # backend :8001, frontend :3000
 *   npm install                      # first time only
 *   node record-user-flow.mjs
 *   ./encode.sh 'out/webm/user-flow/*.webm' out/demo-user-flow
 */

import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import {
  BASE_URL, API_URL, DWELL, TIMING,
  dwell, log, typeInto, inputByLabel, caption, say, apiLogin,
  startRecording, finishRecording, gotoEdit, addStep, savePipeline,
  removeStep, hoverPreview, pickFieldTree, fieldWrap,
} from "./lib.mjs";

const FIXTURE_DIR = "/tmp/dte-samples";
const OUT_DIR = "out/webm/user-flow";

const EMAIL = "admin@admin.com";
const PASSWORD = "admin";

// Stable ids. Setup ensures they exist; if you rename them here the setup
// will create the new ones alongside the old.
const CONN_ID = "local-fs";
const SRC_ID = "orders-json";
const DEST_ID = "orders-output";
const PIPELINE_ID = "orders-demo";
const PIPELINE_NAME = "Orders demo";
const FIXTURE_FILENAME = "orders-demo.json";
const OUTPUT_FILENAME = "orders-demo-output.json";

// ~14 rows so Filter, Sort, and Aggregate each visibly change the preview.
const ORDERS = [
  { order_id: "o01", customer_id: "c1", region: "us-east", amount: 50, status: "paid" },
  { order_id: "o02", customer_id: "c2", region: "us-west", amount: 150, status: "paid" },
  { order_id: "o03", customer_id: "c3", region: "eu", amount: 75, status: "pending" },
  { order_id: "o04", customer_id: "c4", region: "us-east", amount: 300, status: "paid" },
  { order_id: "o05", customer_id: "c5", region: "eu", amount: 220, status: "paid" },
  { order_id: "o06", customer_id: "c6", region: "us-west", amount: 40, status: "paid" },
  { order_id: "o07", customer_id: "c7", region: "eu", amount: 500, status: "paid" },
  { order_id: "o08", customer_id: "c1", region: "us-east", amount: 90, status: "paid" },
  { order_id: "o09", customer_id: "c2", region: "us-west", amount: 175, status: "pending" },
  { order_id: "o10", customer_id: "c3", region: "eu", amount: 260, status: "paid" },
  { order_id: "o11", customer_id: "c4", region: "us-east", amount: 60, status: "paid" },
  { order_id: "o12", customer_id: "c5", region: "us-west", amount: 410, status: "paid" },
  { order_id: "o13", customer_id: "c6", region: "eu", amount: 130, status: "paid" },
  { order_id: "o14", customer_id: "c7", region: "us-east", amount: 780, status: "paid" },
];

// ── setup (off-camera) ─────────────────────────────────────────────────────
/** Ensure the connection, source, destination and fixture file exist. */
async function ensureSetup(req, token) {
  const auth = { Authorization: `Bearer ${token}` };

  // Fixture on disk (bind-mounted into backend at same path).
  const fixturePath = join(FIXTURE_DIR, FIXTURE_FILENAME);
  mkdirSync(FIXTURE_DIR, { recursive: true });
  if (!existsSync(fixturePath)) {
    writeFileSync(fixturePath, JSON.stringify(ORDERS), "utf-8");
    log(`wrote fixture: ${fixturePath}`);
  }

  // Connection
  const cGet = await req.get(`${API_URL}/api/connections/${CONN_ID}`, { headers: auth });
  if (cGet.status() === 404) {
    log(`create connection ${CONN_ID}`);
    const r = await req.post(`${API_URL}/api/connections`, {
      headers: auth,
      data: { id: CONN_ID, connection_type: "local_fs", credentials: {} },
    });
    if (![200, 201].includes(r.status())) {
      throw new Error(`create connection ${r.status()}: ${await r.text()}`);
    }
  } else if (cGet.status() !== 200) {
    throw new Error(`GET connection ${cGet.status()}: ${await cGet.text()}`);
  }
  // Test connection.
  const tRes = await req.post(`${API_URL}/api/connections/${CONN_ID}/test`, { headers: auth });
  const tBody = await tRes.json();
  if (!tBody.ok) throw new Error(`connection test failed: ${tBody.detail ?? "?"}`);
  log(`connection ${CONN_ID} test ok (${tBody.elapsed_ms}ms)`);

  // Source
  const sGet = await req.get(`${API_URL}/api/sources/${SRC_ID}`, { headers: auth });
  if (sGet.status() === 404) {
    log(`create source ${SRC_ID}`);
    const r = await req.post(`${API_URL}/api/sources`, {
      headers: auth,
      data: {
        id: SRC_ID,
        connection_id: CONN_ID,
        source_type: "filesystem",
        config: { bucket_url: FIXTURE_DIR, file_glob: FIXTURE_FILENAME },
        table: "orders",
        format: "json",
      },
    });
    if (![200, 201].includes(r.status())) {
      throw new Error(`create source ${r.status()}: ${await r.text()}`);
    }
  }
  // Test source by fetching its schema — same reachability the UI Infer runs.
  const schema = await req.get(`${API_URL}/api/sources/${SRC_ID}/schema`, { headers: auth });
  if (schema.status() !== 200) {
    throw new Error(`source schema ${schema.status()}: ${await schema.text()}`);
  }
  log(`source ${SRC_ID} schema ok`);

  // Destination
  const dGet = await req.get(`${API_URL}/api/destinations/${DEST_ID}`, { headers: auth });
  if (dGet.status() === 404) {
    log(`create destination ${DEST_ID}`);
    const r = await req.post(`${API_URL}/api/destinations`, {
      headers: auth,
      data: {
        id: DEST_ID,
        connection_id: CONN_ID,
        config: {
          type: "json_file",
          path: join(FIXTURE_DIR, OUTPUT_FILENAME),
          fields: [],
        },
      },
    });
    if (![200, 201].includes(r.status())) {
      throw new Error(`create destination ${r.status()}: ${await r.text()}`);
    }
  }

  // Fresh pipeline every run so history is meaningful.
  const pGet = await req.get(`${API_URL}/api/pipelines/${PIPELINE_ID}`, { headers: auth });
  if (pGet.status() === 200) {
    log(`delete stale pipeline ${PIPELINE_ID}`);
    await req.delete(`${API_URL}/api/pipelines/${PIPELINE_ID}`, { headers: auth });
  }
}

// ── main ───────────────────────────────────────────────────────────────────
async function main() {
  const { req, token } = await apiLogin(EMAIL, PASSWORD);
  await ensureSetup(req, token);

  const rec = await startRecording(OUT_DIR, token);
  const { page } = rec;

  try {
    await page.goto(`${BASE_URL}/`);
    await page.evaluate((tok) => {
      window.localStorage.setItem("dte_token", tok);
      document.cookie = `dte_token=${encodeURIComponent(tok)}; Path=/; SameSite=Lax`;
    }, token);

    // ── 1. New pipeline shell (no steps) ──────────────────────────────────
    log("open /pipelines/new");
    await page.goto(`${BASE_URL}/pipelines/new`);
    await say(
      page,
      "Building a data pipeline in DTE — source, steps, destination, versioned.",
      DWELL.read,
    );

    await caption(page, "Give the pipeline an id and a friendly name.");
    await typeInto(inputByLabel(page, "Pipeline id"), PIPELINE_ID);
    await typeInto(inputByLabel(page, "Name"), PIPELINE_NAME);
    await dwell(DWELL.sm);

    await caption(page, `Pick the source: ${SRC_ID} — a JSON file on disk.`);
    await page.getByRole("button", { name: /— pick a source —/ }).first().click();
    await page.getByRole("option", { name: SRC_ID }).first().click();
    await dwell(DWELL.sm);

    await caption(page, `Pick the destination: ${DEST_ID}.`);
    await page.getByRole("button", { name: /— pick a destination —/ }).first().click();
    await page.getByRole("option", { name: DEST_ID }).first().click();
    await dwell(DWELL.md);

    // Live preview appears on the right — 14 raw rows, no steps yet.
    await hoverPreview(page);
    await say(
      page,
      "Live preview on the right — the raw source, 14 orders across three regions.",
      DWELL.read,
    );

    await caption(page, "Save the empty shell to open the editor with history.");
    await page.getByRole("button", { name: /save pipeline/i }).click();
    await page.waitForURL(new RegExp(`/pipelines/${PIPELINE_ID}$`), { timeout: 15_000 });
    await dwell(DWELL.sm);

    // ── 2. Add all three steps in one editing session — no save between ──
    await gotoEdit(page);
    await say(
      page,
      "Now add steps. The preview on the right dry-runs after every edit — no save required.",
      DWELL.read,
    );

    await addStep(page, "Filter", async () => {
      await caption(page, "Filter — keep only rows where amount > 100.");
      await page.getByRole("button", { name: /add condition/i }).first().click();
      await dwell(TIMING.clickPause);
      const valueInput = page.locator('input[placeholder="value"]').first();
      const row = valueInput.locator("xpath=..");
      await pickFieldTree(row, page, "field", "amount");
      await row.locator("select").first().selectOption(">");
      await dwell(TIMING.clickPause);
      await typeInto(valueInput, "100");
    });
    await hoverPreview(page);
    await say(
      page,
      "Filter applied — the small orders (under 100) are gone from the preview.",
      DWELL.read,
    );

    await addStep(page, "Aggregate", async () => {
      await caption(page, "Aggregate — group by region, sum the amount.");
      await page.getByRole("button", { name: /\+ add group_by field/i }).first().click();
      await dwell(TIMING.clickPause);
      const groupInput = page.locator('input[placeholder="field"]').first();
      const groupRow = groupInput.locator("xpath=..");
      await pickFieldTree(groupRow, page, "field", "region");

      await page.getByRole("button", { name: /\+ add aggregation/i }).first().click();
      await dwell(TIMING.clickPause);
      const aliasInput = page.locator('input[placeholder="gmv"]').first();
      const aggRow = aliasInput.locator("xpath=..");
      await pickFieldTree(aggRow, page, "amount", "amount");
      await typeInto(aliasInput, "total_amount");
    });
    await hoverPreview(page);
    await say(
      page,
      "Aggregate applied — 14 rows collapsed to one per region with a total_amount.",
      DWELL.read,
    );

    // Give /step-schemas (debounced 500ms + RTT) time so Sort sees total_amount.
    await dwell(DWELL.md);
    await addStep(page, "Sort", async () => {
      await caption(page, "Sort — largest total_amount first.");
      const sortInput = page.locator('input[placeholder="add field to sort by…"]').first();
      await sortInput.click();
      await sortInput.type("total", { delay: TIMING.typeDelay });
      await dwell(DWELL.sm);
      await page
        .getByRole("option", { name: /total_amount/i })
        .first()
        .click();
      await dwell(TIMING.clickPause);
      const dir = fieldWrap(page, "Direction").locator("select").first();
      await dir.selectOption("false");
    });
    await hoverPreview(page);
    await say(
      page,
      "Sort applied — biggest total on top. Everything above was a live dry-run.",
      DWELL.read,
    );

    // ── 3. Save all three steps at once ──────────────────────────────────
    await caption(page, "Save. This locks in one revision — three steps at once.");
    await savePipeline(page);
    await dwell(DWELL.md);

    // ── 4. Small edit: remove the Sort step, save again ──────────────────
    await gotoEdit(page);
    await say(page, "Small change — remove the Sort step and let the preview update.", DWELL.md);
    await removeStep(page, "sort");
    await dwell(DWELL.sm);
    await hoverPreview(page);
    await say(
      page,
      "Sort gone — preview is back to unordered totals per region.",
      DWELL.read,
    );

    await caption(page, "Save the edit — a second revision.");
    await savePipeline(page);
    await dwell(DWELL.md);

    // ── 5. History diff between the two edits ────────────────────────────
    await say(page, "Every save is versioned. Open the history panel.", DWELL.md);
    const historyHeading = page.getByText(/^history$/i).first();
    await historyHeading.scrollIntoViewIfNeeded();
    await dwell(DWELL.sm);

    const historySection = page
      .locator("section")
      .filter({ has: page.getByText(/^history$/i) })
      .first();
    const revisions = historySection.locator('button[type="button"]');
    const revCount = await revisions.count().catch(() => 0);
    log(`history revisions: ${revCount}`);
    if (revCount >= 2) {
      await caption(page, "Pick the two most recent edits to diff.");
      await revisions.nth(0).click();
      await dwell(DWELL.sm);
      await revisions.nth(1).click();
      await dwell(DWELL.md);
      // Scroll the DiffView into view.
      const diffHint = page.getByText(/selected for diff/i).first();
      if (await diffHint.isVisible().catch(() => false)) {
        await diffHint.scrollIntoViewIfNeeded();
      }
      await page.mouse.wheel(0, 400);
      await dwell(DWELL.sm);
      await say(
        page,
        "Diff shows exactly what changed between the two revisions.",
        DWELL.read,
      );
    } else {
      log("not enough revisions to diff");
    }

    // ── 6. Trigger a real run and show the output ────────────────────────
    await page.goto(`${BASE_URL}/pipelines/${PIPELINE_ID}`);
    await dwell(DWELL.sm);
    await say(page, "Trigger a real run — this executes end-to-end.", DWELL.md);
    const triggerBtn = page.getByRole("button", { name: /trigger run/i }).first();
    if (await triggerBtn.isVisible().catch(() => false)) {
      await triggerBtn.click();
      await page.waitForURL(/\/runs\//, { timeout: 15_000 });
      await caption(page, "Run in flight…");
      await page
        .getByText(/completed/i)
        .first()
        .waitFor({ state: "visible", timeout: 60_000 });
      await dwell(DWELL.sm);
      // Scroll to the output preview panel on the run detail.
      const outputHead = page.getByText(/output/i).first();
      if (await outputHead.isVisible().catch(() => false)) {
        await outputHead.scrollIntoViewIfNeeded();
      }
      await say(
        page,
        "Completed. Here's the output — one row per region, totals summed.",
        DWELL.read,
      );
    } else {
      log("trigger button not visible — skipping");
    }

    await say(page, "That's DTE — source, steps, destination, versioned.", DWELL.read);
    await caption(page, "");
    log("done");
  } catch (err) {
    console.error("[demo] error:", err.message);
    await page.screenshot({ path: "out/error.png", fullPage: true }).catch(() => {});
    throw err;
  } finally {
    await req.dispose();
    await finishRecording(rec, OUT_DIR);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
