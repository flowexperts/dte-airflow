"use client";

import { useEffect, useRef, useState } from "react";
import { CalEmbed } from "./cal-embed";
import { SiteFooter, TopNav } from "./site-chrome";
import { UseCaseCards } from "./use-case-cards";
import { DOCS_URL, INSTALL_URL, REPO_URL } from "@/lib/site";
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

// What ships in dte-airflow today — keep in step with the README's feature
// tables. No tile without a loader behind it.
const SOURCE_TILES = [
  { mono: "FS", name: "Local files", sub: "json · csv · parquet · xlsx" },
  { mono: "S3", name: "Object storage", sub: "s3 · gcs · azure · sftp" },
  { mono: "PG", name: "Postgres", sub: "tables · queries" },
  { mono: "SQL", name: "SQL databases", sub: "mysql · sql server · sqlite" },
  { mono: "DW", name: "Warehouses", sub: "snowflake · bigquery" },
  { mono: "MDB", name: "MongoDB", sub: "collections" },
  { mono: "API", name: "REST APIs", sub: "paginated · json" },
  { mono: "PDF", name: "PDF documents", sub: "extract · structure" },
];

const DEST_TILES = [
  { mono: "PG", name: "Postgres", sub: "insert · upsert" },
  { mono: "SQL", name: "SQL databases", sub: "mysql · sql server" },
  { mono: "DW", name: "Warehouses", sub: "snowflake · bigquery" },
  { mono: "PQ", name: "Parquet", sub: "s3 · gcs · azure · sftp" },
  { mono: "CSV", name: "CSV files", sub: "for finance · ops" },
  { mono: "XL", name: "Excel", sub: "xlsx" },
  { mono: "JS", name: "JSON files", sub: "json · jsonl" },
];

// Install into an existing Airflow 3.3+, with Airflow's constraints unmodified.
const QUICKSTART = [
  "curl -fsSLo constraints.txt https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt",
  "pip install dte-airflow --constraint constraints.txt",
  "export DTE_DATABASE_URL=postgresql://user:pass@host/dte",
  "dte db upgrade",
];

const LOGIC_STEPS = [
  { idx: "01", op: "filter", expr: <>amount <span className="cmp">&gt;</span> 100</> },
  { idx: "02", op: "rename", expr: <>customer_id <span className="op-arrow">→</span> cust_id</> },
  { idx: "03", op: "lookup", expr: <>iso <span className="op-arrow">→</span> country</> },
  { idx: "04", op: "aggregate", expr: "sum(amount) by cust_id" },
  { idx: "05", op: "join", expr: "customers on cust_id" },
];

// `live: true` means it works in the product today. PDF does: the `extract`
// step ships pypdf and pdfplumber providers, and `structure` turns the text
// into typed columns via Claude, OpenAI or regex. The other three do not —
// there is no OCR provider, no transcription provider and no embedding step,
// so they keep their SOON badge. Do not promote a tile here without a
// provider behind it.
const UNSTRUCTURED_TILES = [
  { mono: "PDF", name: "PDF documents", sub: "text → typed columns", live: true },
  { mono: "IMG", name: "Images", sub: "OCR · vision", live: false },
  { mono: "DOC", name: "Docs & free text", sub: "chunking · embeddings", live: false },
  { mono: "A/V", name: "Audio & video", sub: "transcripts", live: false },
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

  return (
    <div className="mkt-root" data-theme="dark">
      <TopNav />

      <main>
      <section className="hero">
        <div className="wrap hero-grid">
          <div>
            <span className="eyebrow">Open source · Apache Airflow 3</span>
            <h1 className="h-gap-lg">
              Data&nbsp;Transformation<br />Engine.
            </h1>
            <p className="lede lede-hero">
              Powered by <em>Apache Airflow</em>.
            </p>
            <div className="hero-ctas">
              <a href="#quickstart" className="btn primary">
                Quickstart <span className="kbd">↵</span>
              </a>
              <a href={DOCS_URL} className="btn ghost">Docs</a>
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
                  mapped once · <b>runs as an Airflow DAG</b>
                </span>
                <span>1,284 rows · 342 ms</span>
              </div>
            </div>
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

      <section id="quickstart" className="steps-section">
        <div className="wrap">
          <div className="section-head">
            <div className="section-head-copy">
              <span className="section-eyebrow">Quickstart</span>
              <h2>
                One pip install.{" "}<br className="brk" />
                <span className="h2-accent">Into the Airflow you already run.</span>
              </h2>
            </div>
          </div>
          <div className="logic-panel qs-panel">
            <div className="logic-head">
              <span className="dots"><i /><i /><i /></span>
              terminal
            </div>
            <pre className="qs-code">
              {QUICKSTART.map((line) => (
                <code key={line}>
                  <span className="qs-prompt">$ </span>
                  {line}
                </code>
              ))}
            </pre>
          </div>
          <p className="qs-note">
            Add the one-line DAG file, restart Airflow, and find DTE under{" "}
            <b>Plugins ▸ DTE Pipelines</b>. It uses the connections you already have: whatever
            Airflow provider is installed, DTE supports it. Airflow 3.3+, beta, Apache-2.0.
          </p>
          <div className="hero-ctas">
            <a href={INSTALL_URL} className="btn primary">Install guide</a>
            <a href={DOCS_URL} className="btn ghost">Docs</a>
            <a href={REPO_URL} className="btn ghost">GitHub</a>
          </div>
        </div>
      </section>

      <section id="use-cases" className="steps-section">
        <div className="wrap">
          <div className="section-head">
            <div className="section-head-copy">
              <span className="section-eyebrow">Use cases</span>
              <h2>Where will you use DTE?</h2>
            </div>
          </div>
          <UseCaseCards />
        </div>
      </section>

      {/* ponytail: quality section hidden for now — flip to true to bring it back */}
      {false && (
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
      )}

      <section id="unstructured" className="steps-section">
        <div className="wrap">
          <div className="section-head">
            <div className="section-head-copy">
              <span className="section-eyebrow">Now shipping</span>
              <h2>
                Documents in.{" "}
                <span className="h2-accent">Data out.</span>
              </h2>
            </div>
          </div>
          <div className="steps-grid">
            {UNSTRUCTURED_TILES.map((t) => (
              <div
                key={t.mono}
                className={`steps-card${t.live ? "" : " steps-card--soon"}`}
              >
                {!t.live && <span className="steps-soon-badge">SOON</span>}
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
              <span className="section-eyebrow">Production help</span>
              <h2 className="h-gap-md">Want help in production?</h2>
              <ul className="bullets">
                <li>Deploying DTE on your Airflow, sizing, and your first real pipelines.</li>
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

      <SiteFooter />
    </div>
  );
}
