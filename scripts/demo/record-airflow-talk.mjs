/**
 * The Airflow Summit talk demo (slide 12): DTE running *inside* Airflow 3.
 * No captions — Bhavani voices it live over the recording. Light mode.
 *
 *   docker compose up -d --build
 *   node record-airflow-talk.mjs              # → out/webm/airflow-talk/*.webm
 *   ./encode.sh 'out/webm/airflow-talk/*.webm' out/demo-airflow-talk
 *
 * Expects `staging.raw_orders` in postgres-demo and an Airflow connection
 * `warehouse` pointing at it (see setup() for both). Every take resets the
 * pipelines, the DTE source and their DAGs, so run history starts empty.
 */
import { chromium } from "playwright";
import { readFileSync, mkdirSync, rmSync, readdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { CURSOR_INIT, DWELL, TIMING, dwell, humanClick, log, look, openAndPick, typeInto } from "./lib.mjs";

// The talk slot is ~3 min and Bhavani talks over it: tighter than the site demos.
Object.assign(DWELL, { xs: 350, sm: 600, md: 1000, lg: 1500, xl: 2400, read: 3000 });
Object.assign(TIMING, { typeDelay: 28, clickPause: 200 });

const AF = process.env.DEMO_AIRFLOW_URL ?? "http://localhost:8080";
const OUT_DIR = "out/webm/airflow-talk";
const SNAP_DIR = "out/airflow-talk-beats";
const SIZE = { width: 1600, height: 900 };
const PIPE = { name: "orders_clean" };
const CHECKS = { name: "orders_clean_checks" };

// ── API setup ───────────────────────────────────────────────────────────────
const env = Object.fromEntries(
  readFileSync(new URL("../../.env", import.meta.url), "utf8")
    .split("\n").filter((l) => l.includes("=")).map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)]),
);

async function token() {
  const r = await fetch(`${AF}/auth/token`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: "admin", password: env.DTE_ADMIN_PASSWORD }),
  });
  return (await r.json()).access_token;
}

function api(tok) {
  return (method, path, body) => fetch(`${AF}${path}`, {
    method, headers: { Authorization: `Bearer ${tok}`, "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
}

const RAW_ORDERS_SQL = `
CREATE TABLE IF NOT EXISTS staging.raw_orders AS
SELECT order_id::text AS ord_id, customer_id::text AS cust_id,
       to_char(((order_id*37)%50000)/100.0 * CASE WHEN order_id%41=0 THEN -1 ELSE 1 END,'FM99990.00') AS amt,
       to_char(ordered_at,'YYYY-MM-DD HH24:MI:SS') AS ord_dt, lower(currency) AS curr,
       CASE WHEN order_id%97=0 THEN 'test' ELSE status END AS status,
       (order_id%2=0) AS legacy_flag, md5(order_id::text) AS tmp_col
FROM sales.orders;`;

async function setup(tok) {
  const call = api(tok);
  execFileSync("docker", ["exec", "-i", "dte-postgres-demo-1", "psql", "-qU", "demo", "-d", "warehouse"],
    { input: RAW_ORDERS_SQL });
  await call("POST", "/api/v2/connections", {
    connection_id: "warehouse", conn_type: "postgres", description: "Analytics warehouse",
    host: "postgres-demo", port: 5432, login: "demo", password: "demo", schema: "warehouse",
  }); // 409 when it exists — fine.
  for (const pl of await (await call("GET", "/dte/api/pipelines")).json()) {
    if (![PIPE.name, CHECKS.name, "tmp orders"].includes(pl.name)) continue;
    await call("DELETE", `/dte/api/pipelines/${pl.id}`);
    await call("DELETE", `/api/v2/dags/dte__${pl.id}`);
  }
  for (const s of await (await call("GET", "/dte/api/sources")).json()) {
    if (s.id !== s.name || s.id === "warehouse_tmp") await call("DELETE", `/dte/api/sources/${s.id}`);
  }
  // DTE sources over the Airflow connection. Made off-camera: the standalone
  // New source page can't save (it never fills `id`), and inline creation in
  // the builder infers before the table is set and shows a 422.
  for (const [id, schema] of [["warehouse", "staging"], ["warehouse_analytics", "analytics"]]) {
    await call("POST", "/dte/api/sources", {
      id, name: id, connection_id: "warehouse", source_type: "sql_database", config: { schema }, table: "",
    });
  }
  await call("POST", "/dte/api/destinations", {
    id: "orders_clean", name: "orders_clean", connection_id: "warehouse",
    config: { type: "postgres", schema: "analytics", table: "orders_clean", write_disposition: "replace" },
  });
  log("state reset");
}

// ── helpers ─────────────────────────────────────────────────────────────────
let beat = 0;
async function snap(page, name) {
  await page.screenshot({ path: `${SNAP_DIR}/${String(++beat).padStart(2, "0")}-${name}.png` }).catch(() => {});
}

const btn = (page, name) => page.getByRole("button", { name }).first();

async function railMenu(page, rail, item) {
  await humanClick(page, page.getByRole("button", { name: rail, exact: true }));
  await dwell(DWELL.sm);
  await humanClick(page, page.getByRole("menuitem", { name: item }).first());
}

async function goToPipelines(page) {
  await railMenu(page, "Plugins", "DTE Pipelines");
  await dwell(DWELL.xs);
  const transform = page.getByRole("menuitem", { name: /^Transform/ }).first();
  if (await transform.isVisible().catch(() => false)) await humanClick(page, transform);
  await page.getByRole("heading", { name: /pipelines/i }).first().waitFor();
  await dwell(DWELL.md);
}

async function addStep(page, label) {
  await humanClick(page, btn(page, /\+ Add step/));
  await dwell(DWELL.md);
  await humanClick(page, page.getByRole("button", { name: label, exact: true }).first());
  await dwell(DWELL.sm);
}

/** Type into a field-picker input and take the matching option if one pops. */
async function pickField(page, input, name) {
  await typeInto(input, name, page);
  const opt = page.getByRole("option", { name: new RegExp(`^${name}\\b`) }).first();
  await opt.waitFor({ state: "visible", timeout: 8_000 });
  await humanClick(page, opt, { settle: DWELL.xs });
  await dwell(DWELL.xs);
}

async function runNow(page) {
  await humanClick(page, btn(page, /Run$/));
  await humanClick(page, page.getByRole("button", { name: "Run", exact: true }).last());
  await waitForRun(page);
}

async function waitForRun(page) {
  await page.getByText(/^(Completed|Failed)$/).first().waitFor({ timeout: 120_000 });
  await dwell(DWELL.lg);
}

// ── the take ────────────────────────────────────────────────────────────────
async function main() {
  const tok = await token();
  await setup(tok);
  for (const d of [OUT_DIR, SNAP_DIR]) { rmSync(d, { recursive: true, force: true }); mkdirSync(d, { recursive: true }); }

  const browser = await chromium.launch({ headless: !process.env.HEADED });
  const context = await browser.newContext({
    viewport: SIZE, recordVideo: { dir: OUT_DIR, size: SIZE }, deviceScaleFactor: 1, colorScheme: "light",
  });
  await context.addCookies([{ name: "_token", value: tok, url: AF }]);
  await context.addInitScript(() => { try { localStorage.setItem("chakra-ui-color-mode", "light"); } catch {} });
  await context.addInitScript(CURSOR_INIT);
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);

  try {
    // 1 · Airflow home → Plugins ▸ DTE Pipelines: "this lives inside Airflow"
    log("1 · home → plugin");
    await page.goto(`${AF}/`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Plugins", exact: true }).waitFor();
    await dwell(DWELL.lg);
    await goToPipelines(page);
    await snap(page, "pipelines");

    // 2 · Admin ▸ Connections → Admin ▸ DTE Sources picks it up
    log("2 · connections → DTE source");
    await railMenu(page, "Admin", "Connections");
    await page.getByText("warehouse").first().waitFor();
    await look(page, page.getByText("warehouse").first(), DWELL.xl);
    await snap(page, "connections");
    await railMenu(page, "Admin", "DTE Sources");
    await page.getByText("warehouse", { exact: true }).first().waitFor();
    await dwell(DWELL.md);
    await humanClick(page, page.getByText("warehouse", { exact: true }).first());
    await btn(page, /^warehouse/).waitFor();
    await dwell(DWELL.md);
    await humanClick(page, btn(page, /^warehouse/)); // connection picker, held open
    await dwell(DWELL.xl);
    await snap(page, "source-picker");
    await page.keyboard.press("Escape");
    await dwell(DWELL.md);

    // 3 · New pipeline: source → rename, cast, derive, drop → destination
    log("3 · build the pipeline");
    await goToPipelines(page);
    await humanClick(page, btn(page, /New pipeline/));
    await typeInto(page.locator('input[placeholder^="Orders"]'), PIPE.name, page);
    await openAndPick(page, btn(page, /pick a source/), /^warehouse\s/, { browse: DWELL.md });
    await openAndPick(page, btn(page, /pick a table/), /^raw_orders/, { browse: DWELL.md });
    await page.getByRole("button", { name: /^Infer · \d/i }).first().waitFor({ timeout: 30_000 });
    await openAndPick(page, btn(page, /pick a destination/), /^orders_clean/, { browse: DWELL.sm });
    await dwell(DWELL.lg); // live preview fills with the raw rows

    await addStep(page, "Rename");
    const renames = [["ord_id", "order_id"], ["cust_id", "customer_id"], ["amt", "amount"], ["ord_dt", "order_date"], ["curr", "currency"]];
    for (const [i, [from, to]] of renames.entries()) {
      if ((await page.locator('input[placeholder="old_name"]').count()) <= i) {
        await humanClick(page, btn(page, /add mapping/i), { settle: DWELL.xs });
      }
      await pickField(page, page.locator('input[placeholder="old_name"]').nth(i), from);
      await typeInto(page.locator('input[placeholder="new_name"]').nth(i), to, page);
    }
    await dwell(DWELL.md);

    await addStep(page, "Retype");
    await pickField(page, page.getByText("Field", { exact: true }).last().locator("xpath=..").locator("input").first(), "amount");
    await page.locator("select").last().selectOption("float");
    await dwell(DWELL.md);

    await addStep(page, "Map · expression");
    await typeInto(page.locator('input[placeholder="cohort_week"]').last(), "is_refund", page);
    await typeInto(page.locator("textarea").last(), "amount < 0", page);
    await dwell(DWELL.md);

    await addStep(page, "Filter");
    await humanClick(page, page.locator("button:visible", { hasText: /^advanced$/i }).last(), { settle: DWELL.xs });
    await typeInto(page.locator("textarea").last(), "status != 'test'", page);
    await dwell(DWELL.md);

    await addStep(page, "Select / Drop fields");
    await humanClick(page, page.getByRole("radio", { name: "Drop fields" }).last(), { settle: DWELL.xs });
    for (const f of ["legacy_flag", "tmp_col"]) await pickField(page, page.locator('input[placeholder^="add field"]').last(), f);
    await page.keyboard.press("Escape");
    await dwell(DWELL.lg);
    await look(page, page.getByRole("heading", { name: /Live preview/ }), DWELL.xl);
    await snap(page, "built");

    // 5 · Save → Run → Airflow grid goes green → open the task log
    log("5 · save, run, grid, log");
    await humanClick(page, btn(page, /^Save pipeline/));
    await page.waitForURL(/detail\?id=/, { timeout: 20_000 });
    await dwell(DWELL.lg); // DAG gets parsed (refresh interval is 5s)
    PIPE.id = new URL(page.url()).searchParams.get("id");
    await runNow(page);
    await snap(page, "ran");

    await page.goto(`${AF}/dags/dte__${PIPE.id}`, { waitUntil: "domcontentloaded" });
    await page.getByText(/Latest Dag Version/i).waitFor();
    await dwell(DWELL.lg);
    await snap(page, "dag");
    const cell = page.locator('a[href*="/runs/"][href*="/tasks/run"]').first();
    await humanClick(page, cell);
    await page.waitForURL(/\/tasks\//, { timeout: 15_000 });
    await dwell(DWELL.xl * 2); // the log is the payoff; hold on it
    await snap(page, "log");

    // 4 · One quality check, on the table we just wrote
    log("4 · quality check");
    await goToPipelines(page);
    await humanClick(page, btn(page, /New pipeline/));
    await typeInto(page.locator('input[placeholder^="Orders"]'), CHECKS.name, page);
    await humanClick(page, page.getByRole("radio", { name: "Quality Check" }).first());
    await openAndPick(page, btn(page, /pick a source/), /^warehouse_analytics/, { browse: DWELL.sm });
    await openAndPick(page, btn(page, /pick a table/), /^orders_clean/, { browse: DWELL.sm });
    await addStep(page, "Check");
    await typeInto(page.locator('input[placeholder^="Describe what this assertion"]').last(), "every order has an amount and a known currency", page);
    await humanClick(page, page.locator("button:visible", { hasText: /^advanced$/i }).last(), { settle: DWELL.xs });
    await typeInto(page.locator("textarea").last(), "amount IS NOT NULL AND currency IN ('usd', 'eur', 'gbp')", page);
    await dwell(DWELL.lg);
    await snap(page, "check");
    await humanClick(page, btn(page, /^Save pipeline/));
    await page.waitForURL(/detail\?id=/, { timeout: 20_000 });
    await dwell(DWELL.lg);
    await runNow(page);
    await snap(page, "check-ran");

    // 6 · Change a field → save → new DagVersion; set a schedule
    log("6 · change, version, schedule");
    await page.goto(`${AF}/plugin/dte/pipelines/detail?id=${PIPE.id}`, { waitUntil: "domcontentloaded" });
    await page.locator('input[placeholder="new_name"]').first().waitFor();
    await dwell(DWELL.md);
    await addStep(page, "Map · expression");
    await typeInto(page.locator('input[placeholder="cohort_week"]').last(), "is_large_order", page);
    await typeInto(page.locator("textarea").last(), "amount > 250", page);
    await dwell(DWELL.md);
    await humanClick(page, btn(page, /^Save$/));
    await dwell(DWELL.lg);
    await humanClick(page, btn(page, /Set schedule/));
    await dwell(DWELL.lg);
    await snap(page, "schedule");
    await humanClick(page, btn(page, /Create schedule/));
    await dwell(DWELL.lg);
    await humanClick(page, page.getByRole("tab", { name: /History/ }));
    await dwell(DWELL.xl);
    await snap(page, "history");

    // 7 · Run history in Airflow, with the new version
    log("7 · run history");
    await dwell(6_000); // let the dag-processor pick up v2
    await page.goto(`${AF}/dags/dte__${PIPE.id}`, { waitUntil: "domcontentloaded" });
    await page.getByText(/Latest Dag Version/i).waitFor();
    await look(page, page.getByText(/Latest Dag Version/i), DWELL.xl);
    await snap(page, "dag-v2");
    await humanClick(page, page.getByRole("tab", { name: "Runs" }).or(page.getByRole("link", { name: "Runs" })).first());
    await dwell(DWELL.xl);
    await snap(page, "runs");
  } catch (err) {
    await snap(page, "error");
    throw err;
  } finally {
    await context.close();
    await browser.close();
    const files = readdirSync(OUT_DIR).filter((f) => f.endsWith(".webm"));
    if (files.length) log(`recorded: ${join(OUT_DIR, files[0])}`);
  }
}

main().catch((err) => { console.error(err); process.exit(1); });
