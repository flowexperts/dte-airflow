/**
 * Screenshots for docs/user/pipelines/notifications.md: add an email
 * notification to `orders_clean` through the UI (notify-form, notify-panel).
 *
 *   node capture-notifications.mjs   # → ../../docs/user/assets/pipelines/notify-*.png
 *
 * notify-email.png is Mailpit showing a failed run's email:
 *   docker run -d --name dte-mailpit --network dte_default --network-alias mailpit \
 *     -p 127.0.0.1:8025:8025 axllent/mailpit
 * then fail a pipeline that has this notification and shoot localhost:8025.
 *
 * Creates the Airflow smtp connection `team_email` (→ mailpit:1025) and
 * replaces orders_clean's notifications. Light mode, 1440×900 @2x.
 */
import { chromium } from "playwright";
import { readFileSync } from "node:fs";

const AF = process.env.DEMO_AIRFLOW_URL ?? "http://localhost:8080";
const OUT = new URL("../../docs/user/assets/pipelines/", import.meta.url).pathname;
const env = process.env.DTE_ADMIN_PASSWORD ? process.env : Object.fromEntries(
  readFileSync(new URL("../../.env", import.meta.url), "utf8")
    .split("\n").filter((l) => l.includes("=")).map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)]),
);

const tok = await fetch(`${AF}/auth/token`, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ username: "admin", password: env.DTE_ADMIN_PASSWORD }),
}).then((r) => r.json()).then((j) => j.access_token);
const api = (method, p, body) => fetch(`${AF}${p}`, {
  method, headers: { Authorization: `Bearer ${tok}`, "Content-Type": "application/json" },
  body: body && JSON.stringify(body),
}).then((r) => r.json());

await api("DELETE", "/api/v2/connections/team_email").catch(() => {});
await api("POST", "/api/v2/connections", {
  connection_id: "team_email", conn_type: "smtp", host: "mailpit", port: 1025,
  extra: JSON.stringify({ disable_tls: true, disable_ssl: true, from_email: "dte@example.com" }),
});
const pid = (await api("GET", "/dte/api/pipelines")).find((p) => p.name === "orders_clean").id;
await api("PUT", `/dte/api/pipelines/${pid}/notifications`, []);

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: "light" });
await ctx.addCookies([{ name: "_token", value: tok, url: AF }]);
await ctx.addInitScript(() => { try { localStorage.setItem("chakra-ui-color-mode", "light"); } catch {} });
const p = await ctx.newPage();
p.setDefaultTimeout(20_000);

// The panel, not the viewport: it sits below the fold.
const panel = async () => {
  const head = p.getByText("Notifications", { exact: true }).first();
  await head.waitFor();
  await head.evaluate((el) => {
    document.querySelectorAll("[data-shot]").forEach((x) => delete x.dataset.shot);
    while (el.getBoundingClientRect().height < 80) el = el.parentElement;
    el.dataset.shot = "";
    el.scrollIntoView({ block: "center" });
  });
  return p.locator("[data-shot]");
};

await p.goto(`${AF}/plugin/dte/pipelines/detail?id=${pid}`, { waitUntil: "domcontentloaded" });
await panel();
await p.getByRole("button", { name: "+ Add notification" }).click();
await p.getByText("— select a notifier —").click();
await p.getByRole("option", { name: /SmtpNotifier/ }).click();
await p.getByLabel("Success").check();
const modal = p.locator(".fixed.inset-0 > div");
// Each argument is a labelled field; the label isn't bound to its input, so go via the parent.
const field = (name) => modal.locator("label", { hasText: new RegExp(`^${name}`) }).locator("xpath=..").locator("input, textarea").first();
await field("To").fill("data-team@example.com");
await field("From").fill("dte@example.com");
await field("smtp connection").fill("team_email");
await p.waitForTimeout(500);
await modal.screenshot({ path: `${OUT}notify-form.png` });
console.log("✓ notify-form");

await p.getByRole("button", { name: "Add notification", exact: true }).click();
await p.getByText("on failure, success").waitFor();
await p.waitForTimeout(500);
await (await panel()).screenshot({ path: `${OUT}notify-panel.png` });
console.log("✓ notify-panel");

await browser.close();
