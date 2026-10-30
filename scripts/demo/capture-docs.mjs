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

// The Extract example: invoice PDFs → typed columns, from the committed
// corpus compose mounts at /opt/dte/backend/sample_data.
const post = (p, body) => fetch(`${AF}/dte/api${p}`, {
  method: "POST", headers: { Authorization: `Bearer ${tok}`, "Content-Type": "application/json" }, body: JSON.stringify(body),
}).then(async (r) => { if (!r.ok) throw new Error(`POST ${p}: ${r.status} ${await r.text()}`); return r.json(); });
if (!(await get("/pipelines")).some((x) => x.name === "Invoice extract")) {
  const src = (await get("/sources")).find((x) => x.name === "invoices") ?? await post("/sources", {
    name: "invoices", connection_id: "local", source_type: "documents", table: "invoices",
    config: { bucket_url: "/opt/dte/backend/sample_data/eval-demo/invoices/", file_glob: "*.pdf" },
  });
  if (!(await get("/destinations")).some((x) => x.id === "invoice_fields")) await post("/destinations", {
    id: "invoice_fields", connection_id: "local", config: { type: "json", path: "/tmp/dte-samples/out/invoices.json" },
  });
  await post("/pipelines", {
    name: "Invoice extract", sources: [{ source_id: src.id, alias: "invoices" }], output_id: "invoice_fields",
    steps: [
      { op: "extract", source_field: "path", provider: "pdfplumber", granularity: "document", output_field: "content" },
      { op: "structure", input_field: "content", provider: "claude", on_error: "null", model: {
        instructions: "Vendor freight invoices. Read totals as plain numbers.",
        fields: [
          { name: "invoice_number", type: "string", required: true, description: "The invoice id, e.g. INV-1001." },
          { name: "vendor", type: "string", required: true, description: "The company that issued the invoice." },
          { name: "total", type: "float", required: true, description: "The invoice total." },
        ] } },
      { op: "select", fields: ["filename", "invoice_number", "vendor", "total"].map((field) => ({ field })) },
    ],
  });
}
const pipes = await get("/pipelines");
const byName = (n) => pipes.find((p) => p.name === n)?.id ?? (() => { throw new Error(`no pipeline ${n}`); })();
const main = byName("orders_clean");
const checks = byName("orders_clean_checks");
const extract = byName("Invoice extract");
const [run] = await get(`/pipelines/${main}/runs`);
const [checksRun] = await get(`/pipelines/${checks}/runs`);
/** Mark the smallest ancestor of `loc` at least `h` px tall and return it, to shoot one panel. */
const panelOf = async (p, loc, h = 150) => {
  await p.locator("[data-shot]").evaluateAll((es) => es.forEach((e) => delete e.dataset.shot));
  await loc.first().evaluate((el, h) => {
    while (el.getBoundingClientRect().height < h) el = el.parentElement;
    el.dataset.shot = "";
  }, h);
  return p.locator("[data-shot]");
};

const D = `${AF}/plugin/dte`;
const SHOTS = [
  ["pipelines/list.png", `${D}/pipelines`, (p) => p.getByText("orders_clean").first().waitFor()],
  ["pipelines/builder.png", `${D}/pipelines/detail?id=${main}`, (p) => p.getByRole("heading", { name: /Live preview/ }).waitFor()],
  ["pipelines/quality-check.png", `${D}/pipelines/detail?id=${checks}`, (p) => p.getByText(/CHECK/i).first().waitFor()],
  ["pipelines/quality-steps.png", `${D}/pipelines/detail?id=${checks}`, (p) =>
    panelOf(p, p.getByText(/^(ordered steps|steps|checks)$/i).last(), 300)],
  ["pipelines/quality-run.png", `${D}/runs/detail?id=${encodeURIComponent(checksRun.id)}&pipeline=${checks}`, (p) => p.getByText(/Completed|passed/i).first().waitFor()],
  ["pipelines/extract-steps.png", `${D}/pipelines/detail?id=${extract}`, async (p) => {
    await p.setViewportSize({ width: 1440, height: 3000 }); // the panel is taller than a screen
    return panelOf(p, p.getByText(/^(ordered steps|steps)$/i).last(), 300);
  }],
  ["pipelines/extract-preview.png", `${D}/pipelines/detail?id=${extract}`, async (p) => {
    // Structure makes one model call per document (cached after the first).
    await p.getByRole("columnheader", { name: /invoice_number/i }).first().waitFor({ timeout: 300_000 });
  }],
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

// "Your first pipeline", one shot per step. Resets its own objects first.
const call = (method, p) => fetch(`${AF}${p}`, { method, headers: { Authorization: `Bearer ${tok}` } });
async function tutorial(p) {
  const shot = (n, el = p) => el.screenshot({ path: `${OUT}getting-started/first-${n}.png` }).then(() => console.log(`✓ first-${n}`));
  await call("DELETE", "/api/v2/connections/local");
  for (const x of pipes.filter((x) => x.name === "Paid orders")) await call("DELETE", `/dte/api/pipelines/${x.id}`);
  for (const [kind, name] of [["destinations", "orders_paid"], ["sources", "orders"]]) {
    for (const x of (await get(`/${kind}`)).filter((x) => x.name === name)) await call("DELETE", `/dte/api/${kind}/${x.id}`);
  }
  const pick = async (trigger, option) => {
    await trigger.click();
    await p.getByRole("option", { name: option }).first().click();
  };

  // 1 · Airflow connection
  await p.goto(`${AF}/connections`);
  await p.getByRole("button", { name: /Add Connection/i }).click();
  await p.getByLabel(/Connection ID/i).fill("local");
  const type = p.getByLabel(/Connection Type/i);
  await type.click();
  await p.keyboard.type("File (path)");
  await p.keyboard.press("Enter");
  await p.waitForTimeout(800);
  await shot("1-connection");
  await p.getByRole("button", { name: /^Save$/ }).click();
  await p.waitForTimeout(1500);

  // 2 · DTE source. Created through the API: a stack built before the
  // source-form fix (plan 077) can't save a new source from the UI.
  await fetch(`${AF}/dte/api/sources`, {
    method: "POST", headers: { Authorization: `Bearer ${tok}`, "Content-Type": "application/json" },
    body: JSON.stringify({ name: "orders", connection_id: "local", source_type: "filesystem", table: "orders",
      config: { bucket_url: "/tmp/dte-samples/", file_glob: "orders.json" } }),
  }).then(async (r) => { if (!r.ok) throw new Error(`create source: ${r.status} ${await r.text()}`); });
  const src = (await get("/sources")).find((x) => x.name === "orders");
  await p.goto(`${D}/sources/edit?id=${src.id}`);
  await p.getByRole("button", { name: /Infer schema/i }).click();
  await p.getByText("customer", { exact: true }).first().waitFor();
  await shot("2-source");

  // 3 · DTE destination
  await p.goto(`${D}/destinations/new`);
  await p.locator("input").filter({ hasNot: p.locator("[placeholder]") }).first().fill("orders_paid");
  await pick(p.getByRole("button", { name: /pick a connection/ }), /^local\b/);
  await p.locator('input[placeholder="./out/result.json"]').fill("/tmp/dte-samples/out/orders_paid.json");
  await shot("3-destination");
  await p.getByRole("button", { name: /Save destination/ }).click();
  await p.waitForURL((u) => !u.pathname.endsWith("/new"));

  // 4 · pipeline with two steps
  await p.goto(`${D}/pipelines/new`);
  await p.locator('input[placeholder^="Orders"]').fill("Paid orders");
  await pick(p.getByRole("button", { name: /pick a source/ }), /^orders\b/);
  await pick(p.getByRole("button", { name: /pick a destination/ }), /^orders_paid\b/);
  await p.getByRole("button", { name: /\+ Add step/ }).click();
  await p.getByRole("button", { name: "Filter", exact: true }).first().click();
  await p.locator("button:visible", { hasText: /^advanced$/i }).last().click();
  await p.locator("textarea").last().fill("status = 'paid'");
  await p.getByRole("button", { name: /\+ Add step/ }).click();
  await p.getByRole("button", { name: "Select / Drop fields", exact: true }).first().click();
  for (const f of ["id", "customer", "amount"]) {
    await p.locator('input[placeholder^="add field"]').last().fill(f);
    await p.getByRole("option", { name: new RegExp(`^${f}\\b`) }).first().click();
  }
  await p.keyboard.press("Escape");
  await p.getByText("Eli").first().waitFor(); // preview: paid rows only
  await p.waitForTimeout(800);
  const panel = async (text) => {
    await p.locator("[data-shot]").evaluateAll((es) => es.forEach((e) => delete e.dataset.shot));
    await (typeof text === "string" ? p.getByText(text, { exact: true }) : text).first().evaluate((el) => {
      while (el.getBoundingClientRect().height < 150) el = el.parentElement;
      el.dataset.shot = "";
    });
    return p.locator("[data-shot]");
  };
  await shot("4-steps", await panel("Ordered steps"));
  await shot("5-preview", await panel(p.getByRole("heading", { name: /Live preview/ })));

  await p.getByRole("button", { name: /^Save pipeline/ }).click();
  await p.waitForURL(/detail\?id=/);
  await p.waitForTimeout(8000); // dag-processor parses the new DAG
  await p.getByRole("button", { name: /Run$/ }).first().click();
  await p.getByRole("button", { name: "Run", exact: true }).last().click();
  await p.getByText(/^(Completed|Failed)$/).first().waitFor({ timeout: 120_000 });
  await p.waitForTimeout(1000);
  await shot("6-run");
}

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: "light" });
await ctx.addCookies([{ name: "_token", value: tok, url: AF }]);
await ctx.addInitScript(() => { try { localStorage.setItem("chakra-ui-color-mode", "light"); } catch {} });
const page = await ctx.newPage();
page.setDefaultTimeout(20_000);
let failed = 0;
for (const [name, url, ready] of process.env.SKIP_SHOTS ? [] : SHOTS.filter(([n]) => n.includes(process.env.ONLY ?? ""))) {
  try {
    await page.setViewportSize({ width: 1440, height: 900 });
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
if (!process.env.SKIP_TUTORIAL) {
  try { await tutorial(page); } catch (err) {
    failed++;
    await page.screenshot({ path: `${OUT}../tutorial-error.png` });
    console.error(`✗ tutorial: ${err.message.split("\n")[0]}`);
  }
}
await browser.close();
process.exit(failed ? 1 : 0);
