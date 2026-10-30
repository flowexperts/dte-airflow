/**
 * Screenshots for docs/user/assets, taken from a running stack.
 *
 *   docker compose up -d
 *   node record-airflow-talk.mjs   # or any setup with the pipelines below
 *   node capture-docs.mjs          # → ../../docs/user/assets/**
 *
 * Expects pipelines `orders_clean` (with a run and a schedule) and
 * `orders_clean_checks`, DTE sources `warehouse`, destination `orders_clean`
 * and an Airflow connection `warehouse`. Light mode, 1440×900 @2x.
 */
import { chromium } from "playwright";
import { readFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

const AF = process.env.DEMO_AIRFLOW_URL ?? "http://localhost:8080";
const OUT = new URL("../../docs/user/assets/", import.meta.url).pathname;
const env = process.env.DTE_ADMIN_PASSWORD ? process.env : Object.fromEntries(
  readFileSync(new URL("../../.env", import.meta.url), "utf8")
    .split("\n").filter((l) => l.includes("=")).map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)]),
);

const tok = await fetch(`${AF}/auth/token`, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username: "admin", password: env.DTE_ADMIN_PASSWORD }),
}).then((r) => r.json()).then((j) => j.access_token);
const get = (p) => fetch(`${AF}/dte/api${p}`, { headers: { Authorization: `Bearer ${tok}` } }).then((r) => r.json());

const pipes = await get("/pipelines");
const byName = (n) => pipes.find((p) => p.name === n)?.id ?? (() => { throw new Error(`no pipeline ${n}`); })();
const main = byName("orders_clean");
const checks = byName("orders_clean_checks");
const [run] = await get(`/pipelines/${main}/runs`);

const D = `${AF}/plugin/dte`;
const SHOTS = [
  ["getting-started/plugins-menu.png", `${AF}/`, async (p) => {
    await p.getByRole("button", { name: "Plugins", exact: true }).click();
    await p.getByRole("menuitem", { name: "DTE Pipelines" }).first().waitFor();
  }],
  ["pipelines/list.png", `${D}/pipelines`, (p) => p.getByText("orders_clean").first().waitFor()],
  ["pipelines/builder.png", `${D}/pipelines/detail?id=${main}`, (p) => p.getByRole("heading", { name: /Live preview/ }).waitFor()],
  ["pipelines/quality-check.png", `${D}/pipelines/detail?id=${checks}`, (p) => p.getByText(/CHECK/i).first().waitFor()],
  ["pipelines/history.png", `${D}/pipelines/detail?id=${main}`, async (p) => {
    await p.getByRole("tab", { name: /History/ }).click();
  }],
  ["pipelines/schedule.png", `${D}/pipelines/detail?id=${main}`, async (p) => {
    const head = p.getByText("Schedule", { exact: true }).first();
    await head.waitFor();
    // Shoot the panel, not the viewport: it sits below the fold.
    await head.evaluate((el) => {
      while (el.getBoundingClientRect().height < 100) el = el.parentElement;
      el.dataset.shot = "";
    });
    return p.locator("[data-shot]");
  }],
  ["pipelines/run-detail.png", `${D}/runs/detail?id=${encodeURIComponent(run.id)}&pipeline=${main}`, (p) => p.getByText(/Completed/).first().waitFor()],
  ["airflow/dag-grid.png", `${AF}/dags/dte__${main}`, (p) => p.getByText(/Latest Dag Version/i).waitFor()],
  ["airflow/task-log.png", `${AF}/dags/dte__${main}`, async (p) => {
    await p.locator('a[href*="/runs/"][href*="/tasks/run"]').first().click();
    await p.waitForURL(/\/tasks\//);
  }],
  ["connections/airflow-connections.png", `${AF}/connections`, (p) => p.getByText("warehouse").first().waitFor()],
  ["sources/list.png", `${D}/sources`, (p) => p.getByText("warehouse_analytics").first().waitFor()],
  ["sources/edit.png", `${D}/sources/edit?id=warehouse`, (p) => p.getByRole("button", { name: /^warehouse/ }).first().waitFor()],
  ["destinations/edit.png", `${D}/destinations/edit?id=orders_clean`, (p) => p.getByText(/orders_clean/).first().waitFor()],
];

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: "light" });
await ctx.addCookies([{ name: "_token", value: tok, url: AF }]);
await ctx.addInitScript(() => { try { localStorage.setItem("chakra-ui-color-mode", "light"); } catch {} });
const page = await ctx.newPage();
page.setDefaultTimeout(20_000);
let failed = 0;
for (const [name, url, ready] of SHOTS) {
  try {
    await page.goto(url, { waitUntil: "domcontentloaded" });
    const el = await ready(page);
    await page.waitForTimeout(1500); // charts, fonts, the grid's fade-in
    mkdirSync(dirname(OUT + name), { recursive: true });
    await (el?.screenshot ? el : page).screenshot({ path: OUT + name });
    console.log(`✓ ${name}`);
  } catch (err) {
    failed++;
    console.error(`✗ ${name}: ${err.message.split("\n")[0]}`);
  }
}
await browser.close();
process.exit(failed ? 1 : 0);
