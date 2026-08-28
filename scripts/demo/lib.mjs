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
 * Recording size — fixed 16:9, not "whatever this window happens to be".
 *
 * Two demos play on the same landing page, so they must share an aspect
 * ratio or the frame visibly changes shape between sections. Measuring the
 * window gave 1512x862 under Playwright's Chromium and 2560x962 under real
 * Chrome on an external display: 1.75:1 and 2.66:1, from the same script.
 *
 * 1600x900 is the target. `fitViewport` shrinks it to the largest 16:9 rect
 * that fits when the window is smaller, because recordVideo captures at
 * exactly the size it is given and a viewport larger than the window comes
 * back letterboxed with a grey band that cannot be cropped out.
 *
 * Override with DEMO_WIDTH / DEMO_HEIGHT (skips measuring entirely).
 */
const TARGET = { width: 1600, height: 900 };

export const VIEWPORT =
  process.env.DEMO_WIDTH && process.env.DEMO_HEIGHT
    ? { width: Number(process.env.DEMO_WIDTH), height: Number(process.env.DEMO_HEIGHT) }
    : null;

function fitViewport(win) {
  let { width, height } = TARGET;
  if (win.width < width || win.height < height) {
    const scale = Math.min(win.width / width, win.height / height);
    // Even dimensions: H.264 rejects odd ones.
    width = Math.floor((width * scale) / 2) * 2;
    height = Math.floor((height * scale) / 2) * 2;
    console.warn(
      `\x1b[33m[demo]\x1b[0m window is ${win.width}x${win.height}, smaller ` +
      `than the ${TARGET.width}x${TARGET.height} target — recording at ` +
      `${width}x${height} to keep 16:9 without letterboxing.`,
    );
  }
  return { width, height };
}

/**
 * Measure the real maximized window, then fit the 16:9 target inside it.
 * Costs ~2s and one window flash; the alternative is guessing at Chrome's
 * chrome height, which differs across machines and silently letterboxes.
 */
export async function measureWindow() {
  if (VIEWPORT) return VIEWPORT;
  const b = await launchBrowser();
  const c = await b.newContext({ viewport: null });
  const p = await c.newPage();
  await p.goto("about:blank");
  await dwell(800);
  const win = await p.evaluate(() => ({
    width: window.innerWidth,
    height: window.innerHeight,
  }));
  await b.close();
  const size = fitViewport(win);
  log(`recording at ${size.width}x${size.height}`);
  return size;
}

/**
 * Launch options shared by the measuring pass and the real recording.
 *
 * `channel: "chrome"` uses the locally installed Google Chrome instead of
 * Playwright's bundled Chromium, and it is not cosmetic. The bundled build
 * is Chromium 130 (2024) and it broke two things:
 *
 *  - **The PDF inspector.** pdf.js 6.2 computes document fingerprints with
 *    `Uint8Array.prototype.toHex()`, which Chromium 130 does not have. Every
 *    document failed with "Could not open the document — n.toHex is not a
 *    function", so the provenance shot — the strongest fifteen seconds in
 *    the product — recorded an error panel instead.
 *  - **H.264.** The bundled build ships without proprietary codecs, so
 *    nothing could verify the mp4s the site actually serves.
 *
 * Real Chrome fixes both. Falls back to the bundled browser if Chrome is not
 * installed, with a loud warning, because a silent fallback would quietly
 * reintroduce the error panel.
 */
async function launchBrowser(extraArgs = []) {
  const args = ["--start-maximized", ...extraArgs];
  try {
    return await chromium.launch({ headless: false, channel: "chrome", args,
                                   slowMo: TIMING.slowMo });
  } catch {
    console.warn(
      "\x1b[33m[demo]\x1b[0m Google Chrome not found — falling back to " +
      "Playwright's Chromium. The PDF inspector will render an error panel " +
      "(Chromium 130 lacks Uint8Array.prototype.toHex). Install Chrome " +
      "before recording anything that opens a document.",
    );
    return await chromium.launch({ headless: false, args, slowMo: TIMING.slowMo });
  }
}

export const DWELL = { xs: 700, sm: 1200, md: 2000, lg: 3000, xl: 4500, read: 5500 };
export const TIMING = { typeDelay: 55, clickPause: 350, slowMo: 60 };

export const dwell = (ms) => new Promise((r) => setTimeout(r, ms));
export const log = (msg) => console.log(`\x1b[36m[demo]\x1b[0m ${msg}`);

export async function typeInto(loc, text, page = null) {
  if (page) await humanClick(page, loc, { settle: DWELL.xs });
  else await loc.click();
  await loc.fill("");
  await dwell(TIMING.clickPause);
  await loc.type(text, { delay: TIMING.typeDelay });
  await dwell(DWELL.sm);
}

/**
 * The app's Field component renders <label>…</label> without an htmlFor, so
 * Playwright's getByLabel doesn't associate. Navigate by DOM proximity.
 */
export function fieldWrap(page, labelText, which = "first") {
  const labels = page.locator(`label:text-is("${labelText}")`);
  return (which === "last" ? labels.last() : labels.first()).locator("xpath=..");
}

export function inputByLabel(page, labelText, which = "first") {
  return fieldWrap(page, labelText, which).locator("input, textarea").first();
}

/**
 * `which` matters once a pipeline has more than one step: every join editor
 * renders its own Left / Right / How / On / Output id labels, so "first"
 * silently edits the join you added three steps ago. Anything building steps
 * incrementally wants "last".
 */
export async function pickDropdown(page, labelText, optionMatcher, which = "first") {
  const trigger = fieldWrap(page, labelText, which)
    .locator('button[aria-haspopup="listbox"]')
    .first();
  await openAndPick(page, trigger, optionMatcher);
}

/**
 * Open a listbox, hold it open long enough to read, then pick.
 *
 * The hold is the point. A dropdown that opens and closes inside 200ms tells
 * a viewer nothing about what the choices were — and the choices are half of
 * what a builder demo is showing.
 */
export async function openAndPick(page, trigger, optionMatcher, { browse = DWELL.lg } = {}) {
  await humanClick(page, trigger);
  const option = page.getByRole("option", { name: optionMatcher }).first();
  await option.waitFor({ state: "visible", timeout: 10_000 });
  await dwell(browse);
  await humanClick(page, option, { settle: DWELL.sm });
  await dwell(DWELL.sm);
}

/** Pick a value in a tree FieldPicker by typing and choosing the option. */
export async function pickFieldTree(scope, page, placeholder, optionName) {
  const input = scope.locator(`input[placeholder="${placeholder}"]`).first();
  await humanClick(page, input, { settle: DWELL.xs });
  await input.fill("");
  await dwell(TIMING.clickPause);
  await input.type(optionName, { delay: TIMING.typeDelay });
  const opt = page
    .getByRole("option", { name: new RegExp(`^${optionName}\\b`, "i") })
    .first();
  await opt.waitFor({ state: "visible", timeout: 8_000 });
  await dwell(DWELL.md);
  await humanClick(page, opt, { settle: DWELL.xs });
  await dwell(DWELL.sm);
}


// ── synthetic cursor ───────────────────────────────────────────────────────
/**
 * Playwright's video capture does not record the OS pointer, so without this
 * every recording is a series of things changing with no visible cause —
 * menus opening by themselves, fields filling from nowhere. The overlay is
 * driven by real `mousemove` events, so it follows `page.mouse.move()`
 * exactly and needs no separate bookkeeping.
 */
export const CURSOR_INIT = `
  (() => {
    if (window.__demoCursorInstalled) return;
    window.__demoCursorInstalled = true;
    const install = () => {
      if (document.getElementById("__demo-cursor")) return;
      const c = document.createElement("div");
      c.id = "__demo-cursor";
      c.style.cssText = [
        "position:fixed","top:0","left:0","width:22px","height:22px",
        "margin:-2px 0 0 -2px","z-index:2147483646","pointer-events:none",
        "transition:transform 40ms linear","will-change:transform",
      ].join(";");
      c.innerHTML =
        '<svg width="22" height="22" viewBox="0 0 22 22">' +
        '<path d="M3 2l6.5 15.5 2.2-6.1 6.1-2.2z" fill="#fff" ' +
        'stroke="rgba(0,0,0,0.55)" stroke-width="1.2" stroke-linejoin="round"/></svg>';
      const r = document.createElement("div");
      r.id = "__demo-ripple";
      r.style.cssText = [
        "position:fixed","top:0","left:0","width:34px","height:34px",
        "margin:-17px 0 0 -17px","border-radius:50%","pointer-events:none",
        "z-index:2147483645","opacity:0","background:rgba(255,110,60,0.45)",
        "transform:scale(0.3)",
      ].join(";");
      document.body.appendChild(c);
      document.body.appendChild(r);

      const move = (e) => {
        c.style.transform = "translate(" + e.clientX + "px," + e.clientY + "px)";
        r.style.transform = "translate(" + e.clientX + "px," + e.clientY + "px) scale(0.3)";
        r.dataset.x = e.clientX; r.dataset.y = e.clientY;
      };
      document.addEventListener("mousemove", move, true);
      document.addEventListener("mousedown", () => {
        const x = r.dataset.x || 0, y = r.dataset.y || 0;
        r.style.transition = "none";
        r.style.opacity = "0.9";
        r.style.transform = "translate(" + x + "px," + y + "px) scale(0.3)";
        requestAnimationFrame(() => {
          r.style.transition = "transform 380ms ease-out, opacity 380ms ease-out";
          r.style.opacity = "0";
          r.style.transform = "translate(" + x + "px," + y + "px) scale(1.5)";
        });
      }, true);
    };
    if (document.body) install();
    else document.addEventListener("DOMContentLoaded", install);
  })();
`;

/**
 * Move to an element and click it the way a person would: glide there, let
 * the pointer settle so a viewer's eye can arrive before anything changes,
 * then press.
 *
 * `settle` is the pause between arriving and pressing — the single biggest
 * difference between footage that reads as a recording of someone working
 * and footage that reads as a script.
 */
export async function humanClick(page, locator, { settle = DWELL.sm } = {}) {
  const target = locator.first();
  await target.scrollIntoViewIfNeeded().catch(() => {});
  await dwell(DWELL.xs);
  const box = await target.boundingBox().catch(() => null);
  if (!box) { await target.click(); await dwell(settle); return; }
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 26 });
  await dwell(settle);
  await page.mouse.down();
  await dwell(90);
  await page.mouse.up();
  await dwell(TIMING.clickPause);
}

/** Rest the pointer on something without clicking — for reading, not acting. */
export async function look(page, locator, ms = DWELL.md) {
  const target = locator.first();
  await target.scrollIntoViewIfNeeded().catch(() => {});
  const box = await target.boundingBox().catch(() => null);
  if (box) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 22 });
  }
  await dwell(ms);
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
  const browser = await launchBrowser(["--window-position=0,0", "--hide-scrollbars"]);
  const context = await browser.newContext({
    viewport: size,
    recordVideo: { dir: outDir, size },
    // 1, not 2: the video is captured at `size` regardless, so a 2x scale
    // factor just renders 4x the pixels and drops frames on preview refresh.
    deviceScaleFactor: 1,
  });
  await context.addInitScript(CAPTION_INIT);
  await context.addInitScript(CURSOR_INIT);
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

  const accept = page.getByRole("button", { name: /^Add \d+ mappings?$/i });

  if (acceptLowConfidence) {
    // Row checkboxes only. The header carries a select-all checkbox, and
    // clicking that toggles every row at once — including the unmapped ones,
    // which is how you write a column of NULLs into a mart on camera.
    const rows = page.locator("tr").filter({ has: page.locator("input[type=checkbox]") });
    const total = await rows.count();

    for (let i = 0; i < total; i++) {
      // Re-resolve every iteration and bail if the dialog has gone. A stale
      // handle from before the dialog closed just times out for 30s and
      // fails a take that had otherwise already succeeded.
      if (!(await accept.isVisible().catch(() => false))) break;

      const row = rows.nth(i);
      const text = await row.innerText().catch(() => "");
      // Nothing to map: leave it unticked. "no match" is the honest answer
      // and the dialog is right to show it.
      if (/no match/i.test(text)) continue;

      const box = row.locator("input[type=checkbox]").first();
      if (await box.isChecked().catch(() => true)) continue;
      await box.click({ timeout: 5_000 }).catch(() => {});
      await dwell(TIMING.clickPause);
    }
    await dwell(DWELL.md);
  }

  if (await accept.isVisible().catch(() => false)) {
    await accept.click();
  }
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
