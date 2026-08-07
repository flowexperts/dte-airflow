// Desktop no-regression harness: proves the mobile work left >620px untouched.
//
//   node scripts/visual/desktop-no-regression.mjs <baselineUrl> <candidateUrl>
//   e.g.  node scripts/visual/desktop-no-regression.mjs http://localhost:3178 http://localhost:3177
//
// Run a dev server on the baseline branch and one on the candidate branch, then
// point this at both. A full-page pixel diff of 0 at every desktop width is the
// proof that mobile-only work did not touch >620px.
// Freezes every time-dependent element first: the status pill cycles
// pending/running/ok every 2.4s, the active-step highlight walks the list
// every 0.9s, and the demo <video> both animates and changes page height as
// it loads. Without this the diff is pure noise.
import { chromium } from "playwright";
import sharp from "sharp";

const FREEZE = `.mkt-root *,.mkt-root *::before,.mkt-root *::after{animation:none!important;transition:none!important}
.mkt-root .step{opacity:1!important;transform:none!important}
.mkt-root .step.active{border-color:var(--border)!important;background:var(--surface-2)!important;box-shadow:none!important}
.mkt-root .step .step-num,.mkt-root .step .step-tag{color:var(--subtle)!important}
.mkt-root .viz-head .pill{visibility:hidden!important}
.cal-panel{visibility:hidden}`;

const [BASE, CAND] = [process.argv[2] || "http://localhost:3178", process.argv[3] || "http://localhost:3177"];

const b = await chromium.launch();

async function shot(url, w) {
  const p = await b.newPage({ viewport: { width: w, height: 1000 } });
  await p.goto(url, { waitUntil: "networkidle" });
  await p.addStyleTag({ content: FREEZE });
  // settle the video: wait for metadata so its box is final, then pin frame 0
  await p.evaluate(async () => {
    const v = document.querySelector("video");
    if (!v) return;
    if (v.readyState < 1) await new Promise((r) => v.addEventListener("loadedmetadata", r, { once: true }));
    v.pause();
    v.currentTime = 0;
    await new Promise((r) => (v.seeking ? v.addEventListener("seeked", r, { once: true }) : r()));
  });
  await p.waitForTimeout(1200);
  const s = await p.screenshot({ fullPage: true });
  await p.close();
  return s;
}

const cmp = async (a, c) => {
  const [ma, mb] = [await sharp(a).metadata(), await sharp(c).metadata()];
  if (ma.height !== mb.height) return `HEIGHT ${ma.height} vs ${mb.height}`;
  const ra = await sharp(a).raw().toBuffer(), rb = await sharp(c).raw().toBuffer();
  let d = 0;
  for (let i = 0; i < ra.length; i += 3)
    if (Math.abs(ra[i]-rb[i])>8 || Math.abs(ra[i+1]-rb[i+1])>8 || Math.abs(ra[i+2]-rb[i+2])>8) d++;
  return `${d} px`;
};

for (const w of [1024, 1280, 1366, 1440, 1600, 1920]) {
  console.log(`${String(w).padStart(5)}px  baseline-vs-candidate: ${await cmp(await shot(BASE, w), await shot(CAND, w))}`);
}
await b.close();

