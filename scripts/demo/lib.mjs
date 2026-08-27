/**
 * Shared harness for the demo recordings.
 *
 * Everything here was extracted verbatim from record-user-flow.mjs when the
 * second and third recordings appeared — same selectors, same cadence, same
 * caption overlay. Nothing new was invented; if a helper looks odd, the
 * comment explains which bit of the app's DOM forced it.
 *
 * Timing knobs are mutable objects rather than consts because the 90-second
 * cold-email cut runs the same flows at a very different pace:
 *
 *     import { DWELL, TIMING } from "./lib.mjs";
 *     Object.assign(DWELL, { read: 1800, md: 700 });
 *     TIMING.slowMo = 0;
 */

import { chromium, request as pwRequest } from "@playwright/test";
import { mkdirSync, rmSync, readdirSync } from "node:fs";
import { join } from "node:path";

export const BASE_URL = process.env.DEMO_BASE_URL ?? "http://localhost:3000";
export const API_URL = process.env.DEMO_API_URL ?? "http://localhost:8001";

// Deliberately slow — this is a demo, not a test.
/**
 * Recording size. `null` (the default) means "measure the real maximized
 * window and match it exactly" — see measureWindow().
 *
 * This started at a fixed 1280x800 and everything was illegible: the builder
 * is a split pane inside a 220px sidebar shell, so the spec column, the step
 * editor and the preview rail were sharing ~1000px.
 *
 * Do not just raise the numbers. recordVideo captures at exactly the size it
 * is given, and if the browser window is smaller than that the frames get
 * letterboxed with a grey band that cannot be cropped out afterwards. A
 * hardcoded 1512x982 (this display's logical resolution) did exactly that:
 * Chrome's tab strip and address bar take ~87px and the dock takes the rest,
 * leaving 862px of page in a 982px frame.
 *
 * Override for a fixed size (skips the measuring launch):
 *     DEMO_WIDTH=1512 DEMO_HEIGHT=862 node record-core-join.mjs
 */
export const VIEWPORT =
  process.env.DEMO_WIDTH && process.env.DEMO_HEIGHT
    ? { width: Number(process.env.DEMO_WIDTH), height: Number(process.env.DEMO_HEIGHT) }
    : null;

/**
 * Launch a maximized window, ask the page how big it actually is, close it.
 *
 * Costs ~2s and one window flash. The alternative is guessing at Chrome's
 * chrome height, which differs across machines and OS versions and silently
 * letterboxes the asset when it is wrong.
 *
 * `--kiosk` looks like the obvious answer here and is not: it reported
 * 1200x818 on the same display where `--start-maximized` reported 1512x862.
 */
export async function measureWindow() {
  if (VIEWPORT) return VIEWPORT;
  const b = await chromium.launch({ headless: false, args: ["--start-maximized"] });
  const c = await b.newContext({ viewport: null });
  const p = await c.newPage();
  await p.goto("about:blank");
  await dwell(800);
  const size = await p.evaluate(() => ({
    width: window.innerWidth,
    height: window.innerHeight,
  }));
  await b.close();
  log(`recording at ${size.width}x${size.height}`);
  return size;
}

export const DWELL = { xs: 700, sm: 1200, md: 2000, lg: 3000, xl: 4500, read: 5500 };
export const TIMING = { typeDelay: 55, clickPause: 350, slowMo: 60 };

export const dwell = (ms) => new Promise((r) => setTimeout(r, ms));
export const log = (msg) => console.log(`\x1b[36m[demo]\x1b[0m ${msg}`);

export async function typeInto(loc, text) {
  await loc.click();
  await loc.fill("");
  await loc.type(text, { delay: TIMING.typeDelay });
}

/**
 * The app's Field component renders <label>…</label> without an htmlFor, so
 * Playwright's getByLabel doesn't associate. Navigate by DOM proximity.
 */
export function fieldWrap(page, labelText) {
  return page.locator(`label:text-is("${labelText}")`).first().locator("xpath=..");
}

export function inputByLabel(page, labelText) {
  return fieldWrap(page, labelText).locator("input, textarea").first();
}

export async function pickDropdown(page, labelText, optionMatcher) {
  const trigger = fieldWrap(page, labelText)
    .locator('button[aria-haspopup="listbox"]')
    .first();
  await trigger.click();
  await dwell(TIMING.clickPause);
  const option = page.getByRole("option", { name: optionMatcher }).first();
  await option.waitFor({ state: "visible", timeout: 8_000 });
  await option.click();
  await dwell(TIMING.clickPause);
}

/** Pick a value in a tree FieldPicker by typing and choosing the option. */
export async function pickFieldTree(scope, page, placeholder, optionName) {
  const input = scope.locator(`input[placeholder="${placeholder}"]`).first();
  await input.click();
  await input.fill("");
  await input.type(optionName, { delay: TIMING.typeDelay });
  await dwell(TIMING.clickPause);
  const opt = page
    .getByRole("option", { name: new RegExp(`^${optionName}\\b`, "i") })
    .first();
  await opt.waitFor({ state: "visible", timeout: 6_000 });
  await opt.click();
  await dwell(TIMING.clickPause);
}

// ── caption overlay ────────────────────────────────────────────────────────
// Injected as an init script so it survives navigations.
export const CAPTION_INIT = `
  (() => {
    if (window.__demoCaptionInstalled) return;
    window.__demoCaptionInstalled = true;
    const install = () => {
      if (document.getElementById("__demo-caption")) return;
      const el = document.createElement("div");
      el.id = "__demo-caption";
      el.style.cssText = [
        "position:fixed","left:50%","bottom:32px","transform:translateX(-50%)",
        "max-width:900px","padding:14px 22px","background:rgba(15,15,20,0.88)",
        "color:#fff","font:500 17px/1.35 system-ui,-apple-system,sans-serif",
        "letter-spacing:0.01em","border-radius:10px",
        "box-shadow:0 8px 32px rgba(0,0,0,0.35)","z-index:2147483647",
        "opacity:0","transition:opacity 200ms ease","pointer-events:none",
        "text-align:center",
      ].join(";");
      document.body.appendChild(el);
    };
    if (document.body) install();
    else document.addEventListener("DOMContentLoaded", install);
    window.__demoSetCaption = (text) => {
      install();
      const el = document.getElementById("__demo-caption");
      if (!el) return;
      if (!text) { el.style.opacity = "0"; return; }
      el.textContent = text;
      el.style.opacity = "1";
    };
  })();
`;

export async function caption(page, text) {
  await page.evaluate((t) => window.__demoSetCaption(t), text ?? "");
}

export async function say(page, text, ms = DWELL.read) {
  await caption(page, text);
  await dwell(ms);
}

// ── API ────────────────────────────────────────────────────────────────────
export async function apiLogin(email, password) {
  const req = await pwRequest.newContext();
  const r = await req.post(`${API_URL}/api/auth/login`, { data: { email, password } });
  if (r.status() !== 200) {
    await req.dispose();
    throw new Error(`login ${r.status()}: ${await r.text()}`);
  }
  const { access_token } = await r.json();
  return { req, token: access_token };
}

/** GET/PUT/POST/DELETE against the API with the demo bearer token. */
export function api(req, token) {
  const headers = { Authorization: `Bearer ${token}` };
  return {
    get: (p) => req.get(`${API_URL}${p}`, { headers }),
    put: (p, data) => req.put(`${API_URL}${p}`, { headers, data }),
    post: (p, data) => req.post(`${API_URL}${p}`, { headers, data }),
    del: (p) => req.delete(`${API_URL}${p}`, { headers }),
  };
}

// ── recording lifecycle ────────────────────────────────────────────────────
/**
 * Open a recording browser and drop the auth token straight into storage —
 * the UI login is not part of any of these demos and typing a password on
 * camera is worse than useless.
 */
export async function startRecording(outDir, token) {
  try { rmSync(outDir, { recursive: true, force: true }); } catch {}
  mkdirSync(outDir, { recursive: true });

  const size = await measureWindow();
  const browser = await chromium.launch({
    headless: false,
    slowMo: TIMING.slowMo,
    args: ["--start-maximized", "--window-position=0,0", "--hide-scrollbars"],
  });
  const context = await browser.newContext({
    viewport: size,
    recordVideo: { dir: outDir, size },
    // 1, not 2: the video is captured at `size` regardless, so a 2x scale
    // factor just renders 4x the pixels and drops frames on preview refresh.
    deviceScaleFactor: 1,
  });
  await context.addInitScript(CAPTION_INIT);
  const page = await context.newPage();
  page.setDefaultTimeout(30_000);

  await page.goto(`${BASE_URL}/`);
  await page.evaluate((tok) => {
    window.localStorage.setItem("dte_token", tok);
    document.cookie = `dte_token=${encodeURIComponent(tok)}; Path=/; SameSite=Lax`;
  }, token);

  return { browser, context, page };
}

/** Close the context (which flushes the video) and report the file. */
export async function finishRecording({ browser, context }, outDir) {
  await context.close();
  await browser.close();
  const files = readdirSync(outDir).filter((f) => f.endsWith(".webm"));
  if (files.length) log(`recorded: ${join(outDir, files[0])}`);
}

// ── builder interactions ───────────────────────────────────────────────────
/** Navigate from a detail page to the builder for the current pipeline. */
export async function gotoEdit(page) {
  if (/\/edit$/.test(page.url())) return;
  const editBtn = page
    .getByRole("link", { name: /^edit$/i })
    .or(page.getByRole("button", { name: /^edit$/i }))
    .first();
  await editBtn.click();
  await page.waitForURL(/\/pipelines\/.+\/edit$/, { timeout: 10_000 });
  await dwell(DWELL.sm);
}

/** Open the "+ Add step" menu, pick `op`, run the editor — no save. */
export async function addStep(page, op, editorFn) {
  log(`add step: ${op}`);
  const addBtn = page.getByRole("button", { name: /add step/i }).first();
  await addBtn.click();
  await dwell(TIMING.clickPause);
  const opBtn = page
    .getByRole("menuitem", { name: new RegExp(`^${op}$`, "i") })
    .or(page.getByRole("option", { name: new RegExp(`^${op}$`, "i") }))
    .or(page.getByRole("button", { name: new RegExp(`^${op}$`, "i") }))
    .first();
  await opBtn.click();
  await dwell(DWELL.sm);
  if (editorFn) await editorFn();
  await dwell(DWELL.md);
}

/** Click Save on the builder and wait for redirect to the detail page. */
export async function savePipeline(page) {
  await page.getByRole("button", { name: /save pipeline/i }).click();
  await page.waitForURL(/\/pipelines\/[^/]+$/, { timeout: 15_000 });
  await dwell(DWELL.sm);
}

/**
 * Remove a step whose op label (case-insensitive) matches `opLabel` — clicks
 * the `×` button on the first row whose header shows that op.
 */
export async function removeStep(page, opLabel) {
  const row = page
    .locator("div")
    .filter({ hasText: new RegExp(`^\\s*${opLabel}\\b`, "i") })
    .first();
  const removeBtn = row.locator('button[title="Remove"]').first();
  if (!(await removeBtn.isVisible().catch(() => false))) {
    const anyRemove = page.locator('button[title="Remove"]').last();
    await anyRemove.click();
  } else {
    await removeBtn.click();
  }
  await dwell(TIMING.clickPause);
}

/** Hover the live preview panel so the cursor rests on the data. */
export async function hoverPreview(page) {
  const head = page.getByText(/^(live preview|dry run)$/i).first();
  if (await head.isVisible().catch(() => false)) {
    const panel = head.locator("xpath=ancestor::*[contains(@class,'rounded')][1]");
    await panel.hover({ position: { x: 200, y: 100 } }).catch(async () => {
      await head.hover();
    });
  } else {
    await page.mouse.move(940, 400);
  }
  await dwell(DWELL.xs);
}

/**
 * Flip the preview's Data | SQL segmented toggle.
 *
 * The Segmented component renders role="radio", NOT buttons — getByRole
 * ("button", {name: "SQL"}) silently matches nothing and the recording just
 * never switches tabs.
 */
export async function showPreviewTab(page, which) {
  const radio = page.getByRole("radio", { name: new RegExp(`^${which}$`, "i") }).last();
  await radio.click();
  await dwell(DWELL.md);
}

/** Switch the canvas's Spec | Runs | History tabs (role="tab"). */
export async function showTab(page, name) {
  await page.getByRole("tab", { name: new RegExp(`^${name}`, "i") }).first().click();
  await dwell(DWELL.md);
}

/**
 * Open the Auto-map dialog, wait for matching to settle, optionally tick the
 * sub-0.9 rows, and accept.
 *
 * Only rows >= 0.9 are pre-ticked, so the gold `llm` rows are a deliberate
 * click — which is the point of the beat, not an inconvenience. The footer
 * counts up ("Add 6 mappings" -> "Add 11 mappings") as they are ticked.
 */
export async function runAutoMap(page, { acceptLowConfidence = true } = {}) {
  await page.getByRole("button", { name: /Auto-map/i }).first().click();
  // The LLM pass is a real network call on the leftovers; it dominates.
  await page.getByText(/of \d+ accepted/i).first().waitFor({ timeout: 90_000 });
  await dwell(DWELL.read);

  if (acceptLowConfidence) {
    const boxes = page.locator('input[type=checkbox]');
    const n = await boxes.count();
    for (let i = 0; i < n; i++) {
      const box = boxes.nth(i);
      if (await box.isChecked().catch(() => true)) continue;
      // Leave the genuinely unmapped rows alone — ticking a row with no
      // source is how you write NULLs into a mart on camera.
      const row = box.locator("xpath=ancestor::tr[1]");
      const text = await row.innerText().catch(() => "");
      if (/no match/i.test(text)) continue;
      await box.click();
      await dwell(TIMING.clickPause);
    }
    await dwell(DWELL.md);
  }

  await page.getByRole("button", { name: /^Add \d+ mappings?$/i }).click();
  await dwell(DWELL.md);
}

/** Trigger a run through the params modal and wait for a terminal status. */
export async function runPipeline(page, params = {}) {
  await page.getByRole("button", { name: /▶\s*Run/i }).first().click();
  await dwell(DWELL.sm);
  for (const [name, value] of Object.entries(params)) {
    const input = inputByLabel(page, name);
    if (await input.isVisible().catch(() => false)) await typeInto(input, value);
  }
  const go = page
    .getByRole("button", { name: /^(run|run pipeline|start run)$/i })
    .last();
  await go.click();
  await page.getByText(/\b(ok|completed|succeeded|failed)\b/i).first()
    .waitFor({ timeout: 180_000 });
  await dwell(DWELL.lg);
}
