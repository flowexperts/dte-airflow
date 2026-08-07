"use client";

import { useEffect, useRef, useState } from "react";
import { CalEmbed } from "./cal-embed";
import { DemoPlayer } from "./demo-player";
import "./landing.css";

type PillState = "pending" | "running" | "ok";

const CAL_LINK = "bhavaniravi/dte-demo-call";

/** Matches the `phone` breakpoint in landing.css. Keep the two in sync. */
const WIDE_QUERY = "(min-width: 621px)";

const HERO_STEPS = [
  { num: "01", op: "Source", expr: "s3://acme-orders/*.json", tag: "filesystem", cls: "src" },
  { num: "02", op: "Filter", expr: <>amount <span className="cmp">&gt;</span> 100</>, tag: "expr", cls: "" },
  { num: "03", op: "Rename", expr: <>customer_id <span className="op-arrow">→</span> cust_id</>, tag: "rename", cls: "" },
  { num: "04", op: "Aggregate", expr: "sum(amount) by cust_id", tag: "group", cls: "" },
  { num: "05", op: "Join", expr: "customers on cust_id", tag: "left", cls: "" },
  { num: "06", op: "Destination", expr: "postgres://warehouse.public.orders", tag: "postgres", cls: "dest" },
] as const;

const SOURCE_TILES = [
  { mono: "S3", name: "Amazon S3", sub: "json · csv · parquet" },
  { mono: "GCS", name: "Google Cloud", sub: "gcs · hmac" },
  { mono: "AZ", name: "Azure Blob", sub: "connection string" },
  { mono: "PG", name: "Postgres", sub: "table · query" },
  { mono: "MO", name: "MongoDB", sub: "collection" },
  { mono: "RE", name: "REST API", sub: "paginated" },
  { mono: "FS", name: "Filesystem", sub: "local · glob" },
];

const DEST_TILES = [
  { mono: "S3", name: "Amazon S3", sub: "parquet · columnar" },
  { mono: "GCS", name: "Google Cloud", sub: "gcs · hmac" },
  { mono: "AZ", name: "Azure Blob", sub: "connection string" },
  { mono: "PG", name: "Postgres", sub: "upsert · pk" },
  { mono: "SQ", name: "SQL databases", sub: "via dlt" },
  { mono: "JS", name: "JSON file", sub: "json · jsonl" },
  { mono: "CS", name: "CSV file", sub: "flat" },
  { mono: "XL", name: "Excel", sub: "xlsx" },
];

const LOGIC_STEPS = [
  { idx: "01", op: "filter", expr: <>amount <span className="cmp">&gt;</span> 100</> },
  { idx: "02", op: "rename", expr: <>customer_id <span className="op-arrow">→</span> cust_id</> },
  { idx: "03", op: "lookup", expr: <>iso <span className="op-arrow">→</span> country</> },
  { idx: "04", op: "aggregate", expr: "sum(amount) by cust_id" },
  { idx: "05", op: "join", expr: "customers on cust_id" },
];

const ALL_STEPS = [
  { label: "Filter",        hint: "SQL WHERE — GUI builder or raw expression", cat: "transform" },
  { label: "Rename",        hint: "remap column names in bulk",                cat: "transform" },
  { label: "Retype",        hint: "cast to any DuckDB type",                   cat: "transform" },
  { label: "Map · Lookup",  hint: "join a saved lookup table",                 cat: "transform" },
  { label: "Map · Expr",    hint: "derive a new column in SQL",                cat: "transform" },
  { label: "Sort",          hint: "order by any field set, asc or desc",       cat: "transform" },
  { label: "Aggregate",     hint: "group-by with sum · count · avg · min/max", cat: "transform" },
  { label: "Join",          hint: "inner · left · right · outer",              cat: "transform" },
  { label: "Pivot",         hint: "rows → columns (DuckDB PIVOT)",             cat: "transform" },
  { label: "Select / Drop", hint: "keep or strip fields, with aliases",        cat: "transform" },
  { label: "Check",         hint: "assert a rule — fail or warn on breach",    cat: "quality"   },
  { label: "Profile",       hint: "null % · distinct count · min/max stats",   cat: "quality"   },
] as const;

const UNSTRUCTURED_TILES = [
  { mono: "PDF", name: "PDF documents", sub: "text extraction" },
  { mono: "IMG", name: "Images", sub: "OCR · vision" },
  { mono: "DOC", name: "Docs & free text", sub: "chunking · embeddings" },
  { mono: "A/V", name: "Audio & video", sub: "transcripts" },
] as const;

const QUALITY_ROWS = [
  { glyph: "CHK", label: "Check",   hint: "Assert any SQL rule — fail or warn on breach" },
  { glyph: "PRF", label: "Profile", hint: "Null %, distinct count, min/max embedded in the run" },
  { glyph: "PRV", label: "Preview", hint: "20-row dry run — compile errors surface before data moves" },
] as const;

export function LandingPage() {
  const [activeStep, setActiveStep] = useState(-1);
  const [pill, setPill] = useState<PillState>("running");
  const [isWide, setIsWide] = useState(false);
  const stepsRef = useRef<HTMLDivElement | null>(null);
  const flowScrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const mq = window.matchMedia(WIDE_QUERY);
    const sync = () => setIsWide(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    const t = setInterval(() => {
      setActiveStep((i) => (i + 1) % HERO_STEPS.length);
    }, 900);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const states: PillState[] = ["pending", "running", "ok"];
    let i = 1;
    const t = setInterval(() => {
      i = (i + 1) % states.length;
      const next = states[i];
      if (next !== undefined) setPill(next);
    }, 2400);
    return () => clearInterval(t);
  }, []);

  // Land the swipe rail on orders_pipeline rather than on the sources column:
  // the pipeline is the point of the section, and starting mid-diagram makes
  // both directions read as "there is more this way". Rect maths rather than
  // offsetLeft because .flowscroll is not a positioned offsetParent.
  useEffect(() => {
    const rail = flowScrollRef.current;
    if (!rail || isWide) return;
    const logic = rail.querySelector<HTMLElement>(".flowcol.logic");
    if (!logic) return;
    const railBox = rail.getBoundingClientRect();
    const logicBox = logic.getBoundingClientRect();
    rail.scrollLeft += logicBox.left - railBox.left - (railBox.width - logicBox.width) / 2;
  }, [isWide]);

  const currentYear = new Date().getFullYear();

  return (
    <div className="mkt-root" data-theme="dark">
      <nav className="top">
        <div className="wrap">
          <a href="/" className="brand" aria-label="dte">
            dt<span className="e">e</span>
          </a>
          <div className="nav-right">
            <a href="#book" className="btn primary">Request access</a>
          </div>
        </div>
      </nav>

      <main>
      <section className="hero">
        <div className="wrap hero-grid">
          <div>
            <span className="eyebrow">DTE</span>
            <h1 className="h-gap-lg">
              Data&nbsp;Transformation<br />Engine.
            </h1>
            <p className="lede lede-hero">
              Build data pipelines without{" "}
              <em>burning tokens</em> or <em>developer time</em>.
            </p>
            <div className="hero-ctas">
              <a href="#book" className="btn primary">
                Request access <span className="kbd">↵</span>
              </a>
              <a href="#demo" className="btn ghost">See the flow</a>
            </div>
          </div>

          <div className="hero-viz">
            <div className="viz" aria-hidden="true">
              <div className="viz-head">
                <div className="viz-title">
                  <b>orders_pipeline</b>{" "}
                  <span className="viz-title-sub">— 312 source fields · 6 mapped</span>
                </div>
                <div className={`pill ${pill}`}>
                  <span className="dotp" />
                  <span>{pill}</span>
                </div>
              </div>

              <div ref={stepsRef}>
                {HERO_STEPS.map((s, i) => (
                  <div
                    key={s.num}
                    className={`step ${s.cls} ${activeStep === i ? "active" : ""}`.trim()}
                  >
                    <div className="step-num">{s.num}</div>
                    <div className="step-op">
                      {s.op}
                      <span className="expr">{s.expr}</span>
                    </div>
                    <div className="step-tag">{s.tag}</div>
                  </div>
                ))}
              </div>

              <div className="viz-foot">
                <span>
                  mapped once · <b>runs on your schedule</b>
                </span>
                <span>1,284 rows · 342 ms</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="demo" className="demo">
        <div className="wrap">
          <div className="section-head">
            <div className="section-head-copy">
              <h2>
                Transformation Pipeline in minutes.{" "}<br className="brk" />No code, no scripts.
              </h2>
            </div>
          </div>
          <div className="demo-frame">
            <DemoPlayer />
          </div>
        </div>
      </section>

      <section id="flow">
        <div className="wrap">
          <div className="section-head">
            <div className="section-head-copy">
              <span className="section-eyebrow">The flow</span>
              <h2>
                Any source. Your logic.{" "}<br className="brk" />Any destination.
              </h2>
            </div>
          </div>

          {/* Scroll rail is inert above 620px; on phones it lets the grid keep
              its real ~720px width instead of dropping labels or scaling down. */}
          <div className="flowscroll" ref={flowScrollRef}>
          <div className="flowgrid">
            <div className="flowcol">
              <div className="flowcol-title">
                <span className="ft-long">Sources</span>
                <span className="ft-short">Src</span>
              </div>
              <div className="flowcol-body">
                {SOURCE_TILES.map((t) => (
                  <div key={t.mono + t.name} className="tile">
                    <div className="mono">{t.mono}</div>
                    <div className="lbl">
                      <span className="name">{t.name}</span>
                      <span className="sub">{t.sub}</span>
                    </div>
                  </div>
                ))}
                <div className="tile more">
                  <div className="mono">···</div>
                  <div className="lbl">
                    <span className="name">More on request</span>
                    <span className="sub">bring your own</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="flowarrow" aria-hidden="true"><span /></div>

            <div className="flowcol logic">
              <div className="flowcol-title accent">
                <span className="ft-long">Your transformation logic</span>
                <span className="ft-short">Logic</span>
              </div>
              <div className="flowcol-body">
                <div className="logic-panel">
                  <div className="logic-head">
                    <span className="dots"><i /><i /><i /></span>
                    orders_pipeline
                  </div>
                  <div className="logic-steps">
                    {LOGIC_STEPS.map((s) => (
                      <div key={s.idx} className="lstep">
                        <span className="idx">{s.idx}</span>
                        <span className="op">{s.op}</span>
                        <span className="expr">{s.expr}</span>
                      </div>
                    ))}
                  </div>
                  <div className="logic-foot">
                    <span className="pill ok"><span className="dotp" />preview ok</span>
                    <span>1,284 rows</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="flowarrow" aria-hidden="true"><span /></div>

            <div className="flowcol">
              <div className="flowcol-title">
                <span className="ft-long">Destinations</span>
                <span className="ft-short">Dest</span>
              </div>
              <div className="flowcol-body">
                {DEST_TILES.map((t) => (
                  <div key={t.mono + t.name} className="tile dest">
                    <div className="mono">{t.mono}</div>
                    <div className="lbl">
                      <span className="name">{t.name}</span>
                      <span className="sub">{t.sub}</span>
                    </div>
                  </div>
                ))}
                <div className="tile more">
                  <div className="mono">···</div>
                  <div className="lbl">
                    <span className="name">More on request</span>
                    <span className="sub">bring your own</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          </div>
          <div className="flowhint" aria-hidden="true">
            <span>← sources</span>
            <span>destinations →</span>
          </div>
        </div>
      </section>

      <section id="steps" className="steps-section">
        <div className="wrap">
          <div className="section-head">
            <div className="section-head-copy">
              <span className="section-eyebrow">STEPS</span>
              <h2>12 ways to shape your data.</h2>
              <p>Each step is composable and ordered. Mix and match — the pipeline runs them in sequence on every trigger.</p>
            </div>
          </div>
          <div className="steps-grid">
            {ALL_STEPS.map((s) => (
              <div key={s.label} className={`steps-card${s.cat === "quality" ? " steps-card--qa" : ""}`}>
                {s.cat === "quality" && <span className="steps-qa-badge">QA</span>}
                <span className="steps-card-label">{s.label}</span>
                <span className="steps-card-hint">{s.hint}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="quality" className="feat-section">
        <div className="wrap">
          <div className="qa-grid">
            <div className="qa-copy">
              <h2>
                Data Quality?<br />
                <span className="h2-soft">we got it.</span>
              </h2>
              <div className="qa-rows">
                {QUALITY_ROWS.map((r) => (
                  <div key={r.label} className="qa-row">
                    <div className="qa-glyph">{r.glyph}</div>
                    <div>
                      <span className="qa-row-label">{r.label}</span>
                      <span className="qa-row-hint">{r.hint}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="qa-panel" aria-hidden="true">
              <div className="qa-panel-head">
                <span className="dots"><i /><i /><i /></span>
                <span>orders_pipeline · step 4 · check</span>
              </div>
              <div className="qa-checks">
                <div className="qa-check ok">
                  <span className="qa-check-mark">✓</span>
                  <span className="qa-check-expr">amount &gt; 0</span>
                  <span className="qa-check-count">12,847 ok</span>
                </div>
                <div className="qa-check fail">
                  <span className="qa-check-mark">✗</span>
                  <span className="qa-check-expr">customer_id IS NOT NULL</span>
                  <span className="qa-check-count">3 failed</span>
                </div>
                <div className="qa-check warn">
                  <span className="qa-check-mark">⚠</span>
                  <span className="qa-check-expr">country IN (&apos;US&apos;, &apos;EU&apos;)</span>
                  <span className="qa-check-count">42 warned</span>
                </div>
              </div>
              <div className="qa-profile">
                <div className="qa-profile-head">profile · amount</div>
                <div className="qa-profile-stats">
                  <span><b>0%</b> null</span>
                  <span><b>847</b> distinct</span>
                  <span><b>1.20</b> min</span>
                  <span><b>9,420</b> max</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="unstructured" className="steps-section">
        <div className="wrap">
          <div className="section-head">
            <div className="section-head-copy">
              <span className="section-eyebrow eyebrow-blink">Coming soon</span>
              <h2>
                Unstructured data? <span className="h2-accent">Soon.</span>
              </h2>
              <p>PDFs, images, audio, and free text — same pipeline model, once it lands.</p>
            </div>
          </div>
          <div className="steps-grid">
            {UNSTRUCTURED_TILES.map((t) => (
              <div key={t.mono} className="steps-card steps-card--soon">
                <span className="steps-soon-badge">SOON</span>
                <span className="steps-card-label">{t.name}</span>
                <span className="steps-card-hint">{t.sub}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="book" className="book">
        <div className="wrap">
          <div className="book-grid">
            <div className="book-copy">
              <span className="section-eyebrow">Request access</span>
              <h2 className="h-gap-md">See DTE in action.</h2>
              <ul className="bullets">
                <li>No sales pitch. Zero slides.</li>
              </ul>
            </div>
            {/* Desktop gets the inline scheduler. Phones get a plain link out
                to Cal's own mobile flow — the month-view embed renders ~600px
                of dead space then clips mid-month in a bounded panel, and the
                iframe is a heavy payload to ship to a device that never sees
                it. `isWide` gates the mount, so mobile pays nothing. */}
            <div className="cal-panel" aria-label="Cal.com scheduler">
              <div className="cal-head">
                <span className="cal-head-link">
                  cal.com · <b>bhavaniravi/dte-demo-call</b>
                </span>
                <span className="pill ok pill-xs">
                  <span className="dotp" />live
                </span>
              </div>
              <div className="cal-body">{isWide ? <CalEmbed /> : null}</div>
            </div>

            <a
              className="cal-cta btn primary"
              href={`https://cal.com/${CAL_LINK}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              Book a 30-min slot
              <span className="cal-cta-sub">cal.com · opens in a new tab</span>
            </a>
          </div>
        </div>
      </section>
      </main>

      <footer>
        <div className="wrap">
          <div className="foot-left">
            <a href="/" className="brand brand-sm">
              dt<span className="e">e</span>
            </a>
            <span className="copy">data transformation engine · map once, run anytime</span>
          </div>
          <div className="right">
            <a href="#book">Request access</a>
            <span className="copy">© {currentYear}</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
