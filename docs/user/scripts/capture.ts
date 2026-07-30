/**
 * Screenshot capture for docs/user/assets.
 *
 * Usage:
 *   1. Bring up the stack:   docker compose up -d --build
 *   2. Seed + capture:       ./docs/user/scripts/run.sh
 *
 * Env:
 *   DTE_URL       frontend base URL (default http://localhost:3000)
 *   DTE_EMAIL     login email       (default demo@example.com; matches seed.py)
 *   DTE_PASSWORD  login password    (default demopass1234;      matches seed.py)
 */
import { chromium, Page, BrowserContext } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { join, dirname, resolve } from "node:path";

const BASE = process.env.DTE_URL ?? "http://localhost:3000";
const API_BASE = process.env.DTE_API_URL ?? "http://localhost:8001";
const EMAIL = process.env.DTE_EMAIL ?? "demo@example.com";
const PASSWORD = process.env.DTE_PASSWORD ?? "demopass1234";
const OUT = resolve(__dirname, "..", "assets");

type Shot = {
  name: string;             // path under assets/, e.g. "connections/new-local-fs.png"
  route: string;            // path to visit
  wait?: string;            // optional selector to wait for before shot
  actions?: (page: Page) => Promise<void>;
};

// Keep this list aligned with the ![](...) references in docs/user/**/*.md.
// Grep for `!\[` before adding more entries — every entry here should have a
// consumer in the docs, and every doc image should have an entry here.
const SHOTS: Shot[] = [
  { name: "getting-started/pipelines-empty.png", route: "/pipelines", wait: "main" },
  { name: "connections/new-local-fs.png",        route: "/connections/new", wait: "form, main" },
  { name: "sources/new-filesystem.png",          route: "/sources/new",     wait: "form, main" },
  { name: "pipelines/builder-first.png",         route: "/pipelines/orders_paid/edit", wait: "main" },
];

async function authViaApi(ctx: BrowserContext) {
  // The UI login form has an in-flight transition + client-side setToken +
  // router.replace that's fiddly to await deterministically. Hit the API
  // directly, then install the token as the same cookie the app writes.
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status} ${await res.text()}`);
  const { access_token } = (await res.json()) as { access_token: string };
  const url = new URL(BASE);
  await ctx.addCookies([
    { name: "dte_token", value: access_token, domain: url.hostname, path: "/", sameSite: "Lax" },
  ]);
  // Also seed localStorage so client-side code that reads from there works.
  await ctx.addInitScript((token) => {
    try { localStorage.setItem("dte_token", token); } catch {}
  }, access_token);
}

async function main() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  });
  await authViaApi(ctx);
  const page = await ctx.newPage();

  let ok = 0;
  let fail = 0;
  for (const shot of SHOTS) {
    const path = join(OUT, shot.name);
    await mkdir(dirname(path), { recursive: true });
    try {
      await page.goto(`${BASE}${shot.route}`, { waitUntil: "networkidle" });
      if (shot.wait) {
        await page.waitForSelector(shot.wait, { timeout: 10_000 });
      }
      if (shot.actions) await shot.actions(page);
      await page.waitForTimeout(300); // let the layout settle
      await page.screenshot({ path, fullPage: false });
      console.log(`✓ ${shot.name}`);
      ok += 1;
    } catch (err) {
      console.error(`✗ ${shot.name}: ${(err as Error).message}`);
      fail += 1;
    }
  }

  await browser.close();
  console.log(`\n${ok} captured, ${fail} failed`);
  if (fail > 0) process.exit(1);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
