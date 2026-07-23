"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { CalEmbed } from "./cal-embed";
import "./landing.css";

type PillState = "pending" | "running" | "ok";

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
  { mono: "GS", name: "Google Cloud", sub: "gcs · hmac" },
  { mono: "AZ", name: "Azure Blob", sub: "connection string" },
  { mono: "PG", name: "Postgres", sub: "table · query" },
  { mono: "MO", name: "MongoDB", sub: "collection" },
  { mono: "RE", name: "REST API", sub: "paginated" },
  { mono: "FS", name: "Filesystem", sub: "local · glob" },
];

const DEST_TILES = [
  { mono: "PG", name: "Postgres", sub: "upsert · pk" },
  { mono: "SQ", name: "SQL databases", sub: "via dlt" },
  { mono: "S3", name: "Parquet on S3", sub: "columnar" },
  { mono: "JS", name: "JSON file", sub: "json · jsonl" },
  { mono: "CS", name: "CSV file", sub: "flat" },
  { mono: "XL", name: "Excel", sub: "xlsx" },
  { mono: "API", name: "REST endpoint", sub: "on request" },
];

const LOGIC_STEPS = [
  { idx: "01", op: "filter", expr: <>amount <span className="cmp">&gt;</span> 100</> },
  { idx: "02", op: "rename", expr: <>customer_id <span className="op-arrow">→</span> cust_id</> },
  { idx: "03", op: "lookup", expr: <>iso <span className="op-arrow">→</span> country</> },
  { idx: "04", op: "aggregate", expr: "sum(amount) by cust_id" },
  { idx: "05", op: "join", expr: "customers on cust_id" },
];

export function LandingPage() {
  const [activeStep, setActiveStep] = useState(-1);
  const [pill, setPill] = useState<PillState>("running");
  const stepsRef = useRef<HTMLDivElement | null>(null);

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

  const currentYear = new Date().getFullYear();

  return (
    <div className="mkt-root" data-theme="dark">
      <nav className="top">
        <div className="wrap">
          <Link href="/" className="brand" aria-label="dte">
            dt<span className="e">e</span>
          </Link>
          <div className="nav-right">
            <Link href="/pipelines" className="btn plain">Open app</Link>
            <a href="#book" className="btn primary">Book a call</a>
          </div>
        </div>
      </nav>

      <section className="hero">
        <div className="wrap hero-grid">
          <div>
            <span className="eyebrow">DTE</span>
            <h1 style={{ marginTop: 22 }}>
              Data&nbsp;Transformation<br />Engine.
            </h1>
            <p
              className="lede"
              style={{ fontSize: 20, color: "var(--text)", maxWidth: "none" }}
            >
              Map it <em style={{ fontStyle: "normal", color: "var(--accent)", fontWeight: 500 }}>once</em>.
              Run it <em style={{ fontStyle: "normal", color: "var(--accent)", fontWeight: 500 }}>anytime</em>.
            </p>
            <div className="hero-ctas">
              <a href="#book" className="btn primary">
                Book a discovery call <span className="kbd">↵</span>
              </a>
              <a href="#flow" className="btn ghost">See the flow</a>
            </div>
          </div>

          <div className="hero-viz">
            <div className="viz" aria-hidden="true">
              <div className="viz-head">
                <div className="viz-title">
                  <b>orders_pipeline</b>{" "}
                  <span style={{ color: "var(--subtle)" }}>— 312 source fields · 6 mapped</span>
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

      <section id="flow">
        <div className="wrap">
          <div className="section-head" style={{ alignItems: "flex-start" }}>
            <div style={{ minWidth: 0 }}>
              <span className="section-eyebrow">The flow</span>
              <h2 style={{ marginTop: 10 }}>
                Any source. Your logic.
                <br />Any destination.
              </h2>
            </div>
          </div>

          <div className="flowgrid">
            <div className="flowcol">
              <div className="flowcol-title">Sources</div>
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
              <div className="flowcol-title accent">Your transformation logic</div>
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
              <div className="flowcol-title">Destinations</div>
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
      </section>

      <section id="book" className="book">
        <div className="wrap">
          <div className="book-grid">
            <div className="book-copy">
              <span className="section-eyebrow">Book a discovery call</span>
              <h2 style={{ marginTop: 14 }}>See DTE on your data. 30 minutes.</h2>
              <p>
                Bring one real source. We&apos;ll build a pipeline live on the call — map the
                fields, preview the output, and hand you the API to trigger it from your
                scheduler. If DTE isn&apos;t a fit, we&apos;ll tell you before the 30 minutes are up.
              </p>
              <ul className="bullets">
                <li>Bring one messy source and the person who knows what its fields mean.</li>
                <li>Leave with a working pipeline and the endpoint your orchestrator will call.</li>
                <li>No sales pitch. Zero slides.</li>
              </ul>
            </div>
            <div className="cal-panel" aria-label="Cal.com scheduler">
              <div className="cal-head">
                <span>
                  cal.com ·{" "}
                  <b style={{ color: "var(--text)" }}>bhavaniravi/dte-demo-call</b>
                </span>
                <span className="pill ok" style={{ fontSize: "9.5px", padding: "3px 8px" }}>
                  <span className="dotp" />live
                </span>
              </div>
              <div className="cal-body">
                <CalEmbed />
              </div>
            </div>
          </div>
        </div>
      </section>

      <footer>
        <div className="wrap">
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <Link href="/" className="brand" style={{ fontSize: 22 }}>
              dt<span className="e">e</span>
            </Link>
            <span className="copy">data transformation engine · map once, run anytime</span>
          </div>
          <div className="right">
            <Link href="/pipelines">Open app</Link>
            <a href="#book">Book a call</a>
            <span className="copy">© {currentYear}</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
