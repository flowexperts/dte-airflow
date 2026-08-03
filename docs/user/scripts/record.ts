/**
 * Landing-page product demo recorder.
 *
 * Records a real, click-by-click walkthrough of building a pipeline end to
 * end. Playwright doesn't render a hardware cursor into the recorded video,
 * so we inject a DOM cursor that follows page.mouse events.
 *
 * Story (~60s):
 *   1. Pipelines list
 *   2. Click "New pipeline"
 *   3. Type id + name
 *   4. Pick source + destination from dropdowns
 *   5. Add Filter step (via UI), type expression
 *   6. Preview updates
 *   7. Add Aggregate + Sort (via API for editor complexity; UI shows result)
 *   8. Click Save
 *   9. Trigger run
 *  10. Run detail → completed
 *
 * Output: docs/user/assets/landing/dte-demo.webm
 * The driver (record.sh) transcodes to mp4 into frontend/public/marketing/.
 */
import { chromium, Page, BrowserContext } from "@playwright/test";
import { mkdir, rename, readdir, rm } from "node:fs/promises";
import { resolve } from "node:path";

const BASE = process.env.DTE_URL ?? "http://localhost:3000";
const API_BASE = process.env.DTE_API_URL ?? "http://localhost:8001";
const EMAIL = process.env.DTE_EMAIL ?? "demo@example.com";
const PASSWORD = process.env.DTE_PASSWORD ?? "demopass1234";

const OUT_DIR = resolve(__dirname, "..", "assets", "landing");
const OUT_FILE = "dte-demo.webm";
const VIEWPORT = { width: 1440, height: 900 };

// The demo pipeline is upserted below by its user-facing NAME (unique per
// tenant). Its id is opaque and server-generated on first create; we resolve
// name → id once at startup so subsequent /api/pipelines/<id>/... calls
// point at the right row.
const PIPE_NAME = "Customer revenue";
const SOURCE_ID = "docs_demo_orders";   // seeded by seed.py, id-stable
const DEST_ID = "docs_demo_orders_paid"; // seeded by seed.py, id-stable

let PIPE_ID = "";

let TOKEN = "";
// Playwright doesn't expose current mouse position; track it ourselves so
// smooth moves know where to start from.
const mouse = { x: VIEWPORT.width / 2, y: VIEWPORT.height / 2 };

/* ── API helpers ─────────────────────────────────────────────────── */

async function api(path: string, init: RequestInit = {}) {
  return fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init.headers as Record<string, string> | undefined),
      "content-type": "application/json",
      ...(TOKEN ? { authorization: `Bearer ${TOKEN}` } : {}),
    },
  });
}

async function login() {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status} ${await res.text()}`);
  TOKEN = ((await res.json()) as { access_token: string }).access_token;
}

async function installAuth(ctx: BrowserContext) {
  const url = new URL(BASE);
  await ctx.addCookies([
    { name: "dte_token", value: TOKEN, domain: url.hostname, path: "/", sameSite: "Lax" },
  ]);
  await ctx.addInitScript((t) => {
    try { localStorage.setItem("dte_token", t); } catch {}
  }, TOKEN);
}

async function resolvePipelineIdByName(name: string): Promise<string> {
  const r = await api(`/api/pipelines?limit=1000`);
  if (!r.ok) return "";
  const list = (await r.json()) as { id: string; name: string }[];
  return list.find((p) => p.name === name)?.id ?? "";
}

async function resetPipeline() {
  PIPE_ID = await resolvePipelineIdByName(PIPE_NAME);
  if (PIPE_ID) {
    await api(`/api/pipelines/${PIPE_ID}`, { method: "DELETE" });
    PIPE_ID = "";
  }
}

async function patchPipeline(steps: unknown[]) {
  const body: Record<string, unknown> = {
    name: PIPE_NAME,
    sources: [SOURCE_ID],
    output_id: DEST_ID,
    steps,
  };
  if (PIPE_ID) {
    // Update in place — id is opaque, path carries the server-side UUID.
    body.id = PIPE_ID;
    const r = await api(`/api/pipelines/${PIPE_ID}`, { method: "PUT", body: JSON.stringify(body) });
    if (r.ok) return;
    if (r.status !== 404) throw new Error(`patch pipeline: ${r.status} ${await r.text()}`);
    PIPE_ID = "";
  }
  // Create — server generates the id; capture it for subsequent calls.
  const r = await api(`/api/pipelines`, { method: "POST", body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`patch pipeline: ${r.status} ${await r.text()}`);
  PIPE_ID = ((await r.json()) as { id: string }).id;
}

/* ── Injected cursor ─────────────────────────────────────────────── */

const CURSOR_SCRIPT = `
(function () {
  function install() {
    if (document.getElementById('__demo_cursor')) return;
    const c = document.createElement('div');
    c.id = '__demo_cursor';
    c.style.cssText = [
      'position:fixed', 'top:0', 'left:0',
      'width:28px', 'height:28px',
      'pointer-events:none', 'z-index:2147483646',
      'transform:translate3d(0,0,0)',
      'filter:drop-shadow(0 2px 4px rgba(0,0,0,0.6))',
    ].join(';');
    c.innerHTML =
      '<svg viewBox="0 0 28 28" xmlns="http://www.w3.org/2000/svg" style="display:block">' +
      '<path d="M4 3 L4 22 L9.5 17 L13 25 L16.5 23.5 L13 15.5 L21 15.5 Z"' +
      ' fill="#ffffff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/>' +
      '</svg>';
    document.body.appendChild(c);

    const ripple = document.createElement('div');
    ripple.id = '__demo_ripple';
    ripple.style.cssText = [
      'position:fixed', 'top:0', 'left:0',
      'width:36px', 'height:36px', 'border-radius:50%',
      'border:2px solid rgba(255,90,31,0.9)',
      'pointer-events:none', 'z-index:2147483645',
      'transform:translate(-50%,-50%) scale(0.3)', 'opacity:0',
    ].join(';');
    document.body.appendChild(ripple);

    window.__demoMoveCursor = function (x, y) {
      c.style.transform = 'translate3d(' + x + 'px,' + y + 'px, 0)';
    };
    window.__demoClickAt = function (x, y) {
      ripple.style.transition = 'none';
      ripple.style.left = x + 'px';
      ripple.style.top = y + 'px';
      ripple.style.opacity = '1';
      ripple.style.transform = 'translate(-50%,-50%) scale(0.3)';
      requestAnimationFrame(function () {
        ripple.style.transition = 'transform 500ms ease-out, opacity 500ms ease-out';
        ripple.style.transform = 'translate(-50%,-50%) scale(1.8)';
        ripple.style.opacity = '0';
      });
    };
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', install);
  } else {
    install();
  }
})();
`;

/* ── Mouse motion + click primitives ─────────────────────────────── */

async function moveTo(page: Page, x: number, y: number, steps = 24) {
  // Animate the injected cursor in tandem with Playwright's virtual mouse.
  // We drive it explicitly rather than relying on mousemove listeners so it
  // still moves when travelling over regions that don't propagate events.
  const from = { x: mouse.x, y: mouse.y };
  await page.evaluate(({ CURSOR_SCRIPT }) => {
    // ensure cursor exists (idempotent)
    // eslint-disable-next-line no-eval
    eval(CURSOR_SCRIPT);
  }, { CURSOR_SCRIPT }).catch(() => {});
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    const ease = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t; // easeInOutQuad
    const nx = from.x + (x - from.x) * ease;
    const ny = from.y + (y - from.y) * ease;
    await page.mouse.move(nx, ny);
    await page.evaluate(({ nx, ny }) => window.__demoMoveCursor?.(nx, ny), { nx, ny });
    await page.waitForTimeout(12);
  }
  mouse.x = x;
  mouse.y = y;
}

async function moveToLocator(page: Page, factory: () => ReturnType<Page["locator"]>) {
  const loc = factory().first();
  await loc.scrollIntoViewIfNeeded().catch(() => {});
  const box = await loc.boundingBox();
  if (!box) throw new Error("moveToLocator: no bounding box");
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await moveTo(page, x, y);
  return { x, y };
}

async function clickLocator(page: Page, factory: () => ReturnType<Page["locator"]>) {
  const { x, y } = await moveToLocator(page, factory);
  await page.waitForTimeout(180);
  await page.evaluate(({ x, y }) => window.__demoClickAt?.(x, y), { x, y });
  await factory().first().click();
}

async function typeInto(page: Page, factory: () => ReturnType<Page["locator"]>, text: string, perChar = 40) {
  await clickLocator(page, factory);
  await factory().first().fill(""); // reset
  for (const ch of text) {
    await page.keyboard.type(ch);
    await page.waitForTimeout(perChar);
  }
}

/* ── Captions ────────────────────────────────────────────────────── */

async function caption(page: Page, text: string, hold = 900) {
  await page.evaluate(({ text }) => {
    let el = document.getElementById("__demo_caption") as HTMLDivElement | null;
    if (!el) {
      el = document.createElement("div");
      el.id = "__demo_caption";
      el.style.cssText = [
        "position:fixed", "left:50%", "top:24px", "transform:translateX(-50%)",
        "background:rgba(15,15,15,0.92)", "color:#fff", "padding:10px 20px",
        "border-radius:999px", "font:500 14px/1 Outfit, system-ui, sans-serif",
        "letter-spacing:0.01em", "z-index:2147483647",
        "box-shadow:0 6px 24px rgba(0,0,0,0.4)", "opacity:0",
        "transition:opacity 200ms ease",
      ].join(";");
      document.body.appendChild(el);
    }
    el.textContent = text;
    requestAnimationFrame(() => { el!.style.opacity = "1"; });
  }, { text });
  await page.waitForTimeout(hold);
}

async function hideCaption(page: Page) {
  await page.evaluate(() => {
    const el = document.getElementById("__demo_caption");
    if (el) el.style.opacity = "0";
  });
  await page.waitForTimeout(180);
}

/* ── Zoom (used sparingly, on the preview) ───────────────────────── */

async function zoomTo(page: Page, factory: () => ReturnType<Page["locator"]>, scale = 1.5, hold = 1400) {
  const loc = factory().first();
  await loc.scrollIntoViewIfNeeded().catch(() => {});
  const box = await loc.boundingBox().catch(() => null);
  if (!box) return;
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await page.evaluate(({ cx, cy, scale, w, h }) => {
    const originX = (cx / w) * 100;
    const originY = (cy / h) * 100;
    document.body.style.transition = "transform 500ms ease";
    document.body.style.transformOrigin = `${originX}% ${originY}%`;
    document.body.style.transform = `scale(${scale})`;
  }, { cx, cy, scale, w: VIEWPORT.width, h: VIEWPORT.height });
  await page.waitForTimeout(hold);
}

async function zoomOut(page: Page, hold = 300) {
  await page.evaluate(() => { document.body.style.transform = "scale(1)"; });
  await page.waitForTimeout(hold);
}

/* ── The story ───────────────────────────────────────────────────── */

async function goto(page: Page, path: string) {
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" });
  // Re-inject cursor after each navigation (init script fires but the DOM
  // is fresh — the script is idempotent so this is safe).
  await page.evaluate(CURSOR_SCRIPT);
  await page.waitForTimeout(400);
}

const FILTER_STEP = { op: "filter", expr: "\"status\" = 'paid'" };
const AGG_STEP = {
  op: "aggregate",
  group_by: ["customer"],
  aggregations: [{ field: "amount", func: "sum", alias: "total" }],
};
const SORT_STEP = { op: "sort", by: ["total"], ascending: false };

async function main() {
  await mkdir(OUT_DIR, { recursive: true });

  await login();
  await resetPipeline();

  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 1,
    recordVideo: { dir: OUT_DIR, size: VIEWPORT },
  });
  await installAuth(ctx);
  await ctx.addInitScript({ content: CURSOR_SCRIPT });
  const page = await ctx.newPage();

  /* Scene 1 — pipelines list */
  await goto(page, "/pipelines");
  await caption(page, "Every pipeline you've built.");
  await moveTo(page, 400, 300);
  await page.waitForTimeout(700);
  await hideCaption(page);

  /* Scene 2 — click New pipeline */
  await caption(page, "Start a new one.");
  await clickLocator(page, () => page.getByRole("link", { name: /new pipeline/i }));
  await page.waitForURL(/\/pipelines\/new/, { timeout: 5000 }).catch(() => {});
  await page.evaluate(CURSOR_SCRIPT);
  await hideCaption(page);

  /* Scene 3 — type name (id is server-generated) */
  await caption(page, "Give it a name.");
  await typeInto(page, () => page.locator('input').first(), PIPE_NAME);
  await hideCaption(page);

  /* Scene 4 — pick source + destination.
     The empty-form path requires opening two dropdowns; that flow is
     dropdown-portal heavy and flaky. Persist state via API, then continue
     on the edit page where source + destination are already picked.
     From the user's PoV the click on "Save pipeline" later commits everything. */
  await patchPipeline([]);
  await goto(page, `/pipelines/${PIPE_ID}/edit`);
  await caption(page, "Source picked. Destination picked.");
  await moveToLocator(page, () => page.getByText(/sources/i).first());
  await page.waitForTimeout(700);
  await moveToLocator(page, () => page.getByText(/^destination$/i).first());
  await page.waitForTimeout(700);
  await hideCaption(page);

  /* Scene 5 — Add a Filter step via the actual UI */
  await caption(page, "Add a filter step.");
  await clickLocator(page, () => page.getByRole("button", { name: /add step/i }));
  await page.waitForTimeout(300);
  await clickLocator(page, () => page.getByRole("button", { name: /^Filter$/ }).first());
  await page.waitForTimeout(600);
  await hideCaption(page);

  /* Scene 6 — Type the filter expression in the Advanced tab */
  await caption(page, "Keep only paid orders.");
  const advanced = page.getByRole("button", { name: /advanced/i }).first();
  if (await advanced.count() > 0) {
    await clickLocator(page, () => advanced);
    await page.waitForTimeout(300);
  }
  const filterInput = page.locator("textarea").first();
  await clickLocator(page, () => filterInput);
  await filterInput.fill("");
  for (const ch of `"status" = 'paid'`) {
    await page.keyboard.type(ch);
    await page.waitForTimeout(30);
  }
  await page.waitForTimeout(400);
  await hideCaption(page);

  /* Scene 7 — Preview updates */
  await caption(page, "Live preview updates as you edit.");
  await zoomTo(page, () => page.getByText(/live preview/i), 1.4, 1600);
  await zoomOut(page);
  await hideCaption(page);

  /* Scene 8 — Aggregate + Sort (via API, then reload to show the result) */
  await patchPipeline([FILTER_STEP, AGG_STEP]);
  await goto(page, `/pipelines/${PIPE_ID}/edit`);
  await caption(page, "Aggregate — total revenue per customer.");
  await moveToLocator(page, () => page.getByText(/^aggregate$/i).first());
  await page.waitForTimeout(800);
  await zoomTo(page, () => page.getByText(/live preview/i), 1.4, 1500);
  await zoomOut(page);
  await hideCaption(page);

  await patchPipeline([FILTER_STEP, AGG_STEP, SORT_STEP]);
  await goto(page, `/pipelines/${PIPE_ID}/edit`);
  await caption(page, "Sort — highest first.");
  await moveToLocator(page, () => page.getByText(/^sort$/i).first());
  await page.waitForTimeout(600);
  await zoomTo(page, () => page.getByText(/live preview/i), 1.4, 1500);
  await zoomOut(page);
  await hideCaption(page);

  /* Scene 9 — Save */
  await caption(page, "Save.");
  await clickLocator(page, () => page.getByRole("button", { name: /save pipeline/i }));
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.evaluate(CURSOR_SCRIPT);
  await page.waitForTimeout(800);
  await hideCaption(page);

  /* Scene 10 — Detail page: history + trigger */
  await goto(page, `/pipelines/${PIPE_ID}`);
  await caption(page, "Every save is versioned.");
  await moveToLocator(page, () => page.getByText(/history/i));
  await page.waitForTimeout(1200);
  await hideCaption(page);

  await caption(page, "Trigger a run.");
  const trigger = page.getByRole("button", { name: /^(run|trigger)/i }).first();
  await clickLocator(page, () => trigger);
  await page.waitForTimeout(500);
  await hideCaption(page);

  /* Scene 11 — Run detail, wait for completion */
  await page.waitForURL(/\/runs\//, { timeout: 8000 }).catch(async () => {
    const r = await api(`/api/pipelines/${PIPE_ID}/runs?limit=1`);
    if (r.ok) {
      const runs = (await r.json()) as { id: string }[];
      if (runs[0]) await goto(page, `/runs/${runs[0].id}`);
    }
  });
  await page.evaluate(CURSOR_SCRIPT);
  await caption(page, "Runs stream status until they're done.");
  await page.locator("text=/completed|failed/i").first().waitFor({ timeout: 20_000 }).catch(() => {});
  await page.waitForTimeout(800);
  await hideCaption(page);

  await caption(page, "Map it once. Run it forever.", 1800);
  await page.waitForTimeout(600);
  await hideCaption(page);
  await page.waitForTimeout(400);

  const video = page.video();
  await ctx.close();
  await browser.close();

  if (!video) throw new Error("no video produced");
  const src = await video.path();
  const dest = resolve(OUT_DIR, OUT_FILE);
  try { await rm(dest); } catch {}
  await rename(src, dest);
  console.log(`✓ ${dest}`);
  for (const d of await readdir(OUT_DIR, { withFileTypes: true })) {
    if (d.isDirectory()) {
      try { await rm(resolve(OUT_DIR, d.name), { recursive: true }); } catch {}
    }
  }
}

declare global {
  interface Window {
    __demoClickAt?: (x: number, y: number) => void;
    __demoMoveCursor?: (x: number, y: number) => void;
    __demoCursorInstalled?: boolean;
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
