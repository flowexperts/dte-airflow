// Responsive sweep for the marketing landing page.
//
//   node scripts/visual/responsive-sweep.mjs [url]     default http://localhost:3000
//
// Reports, per viewport width:
//   - scrollW vs viewport      any horizontal overflow (.mkt-root has
//                              overflow-x:hidden, so overflow is CLIPPED, not
//                              visible — this is the only way to catch it)
//   - pageH                    total page height, i.e. how much thumb it costs
//   - iframes                  should be 0 on phones (Cal embed is desktop-only)
//   - heroViz / cal            which layout branch is live
//   - section order            #unstructured moves below #book under 620px
//
// Requires: pnpm add -D playwright sharp && npx playwright install chromium
// Deliberately NOT in package.json — Cloudflare Pages should not install it.
import { chromium } from "playwright";

const URL = process.argv[2] || "http://localhost:3000/";
const WIDTHS = [320, 360, 390, 414, 620, 768, 900, 1000, 1024, 1280, 1440];

const browser = await chromium.launch();

for (const w of WIDTHS) {
  const page = await browser.newPage({ viewport: { width: w, height: 800 } });
  await page.goto(URL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  const r = await page.evaluate(() => {
    const dw = document.documentElement.clientWidth;
    // .flowscroll is a deliberate horizontal scroll rail on phones — its
    // children are *supposed* to extend past the viewport. Only unintended
    // overflow counts, so exclude anything inside it.
    const bad = [...document.querySelectorAll(".mkt-root *")]
      .filter((e) => !e.closest(".flowscroll"))
      .filter((e) => {
        const b = e.getBoundingClientRect();
        return b.width > 0 && (b.right > dw + 1 || b.left < -1);
      })
      .map((e) => `${e.tagName.toLowerCase()}.${e.getAttribute("class") || ""}`);
    const disp = (sel) => {
      const e = document.querySelector(sel);
      return e ? getComputedStyle(e).display : "absent";
    };
    return {
      scrollW: document.documentElement.scrollWidth,
      pageH: document.documentElement.scrollHeight,
      bad: [...new Set(bad)].slice(0, 5),
      iframes: document.querySelectorAll("iframe").length,
      heroViz: disp(".hero-viz"),
      calPanel: disp(".cal-panel"),
      calCta: disp(".cal-cta"),
      // display:none reports top 0, which would sort a hidden section to the
      // front and read as a reorder bug. Drop them and mark them instead.
      hidden: [...document.querySelectorAll("main > section")]
        .filter((s) => getComputedStyle(s).display === "none")
        .map((s) => s.id || s.className),
      order: [...document.querySelectorAll("main > section")]
        .filter((s) => getComputedStyle(s).display !== "none")
        .map((s) => ({ id: s.id || s.className, top: s.getBoundingClientRect().top + scrollY }))
        .sort((a, b) => a.top - b.top)
        .map((s) => s.id),
    };
  });

  const status = r.bad.length ? `OVERFLOW ${r.bad.join(" | ")}` : "clean";
  console.log(
    `${String(w).padStart(5)}px scrollW=${r.scrollW} pageH=${r.pageH} iframes=${r.iframes} ` +
      `heroViz=${r.heroViz} cal=${r.calPanel}/${r.calCta} ${status}`
  );
  if (w === 360 || w === 1280) {
    console.log(`        order: ${r.order.join(" -> ")}`);
    if (r.hidden.length) console.log(`        hidden: ${r.hidden.join(", ")}`);
  }

  await page.close();
}

await browser.close();
