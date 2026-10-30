"use client";

import { useEffect, useRef } from "react";

/** The hero window: a cursor adds three steps in the builder, the preview
 *  reacts, Run is pressed, and Airflow's grid shows the DAG succeed. Modelled
 *  on docs/user/assets/pipelines/builder.png and airflow/dag-grid.png.
 *  Imperative on purpose — it's a timeline, not state. */

// The first step is the AI one: Structure fields turns PDF text into typed
// columns (docs/user/steps/index.md, "Documents (PDF)").
const STEPS = [
  ["structure", "invoice_no · vendor · total", "claude"],
  ["filter", "total > 100", ""],
  ["check", "total IS NOT NULL", ""],
] as const;

const ROWS = [
  ["0412", "Acme Supply", "42.00"],
  ["0413", "Northwind", "180.50"],
  ["0414", "Bluebird Co", "96.10"],
  ["0415", "Kestrel Ltd", "312.00"],
  ["0416", "Orchard & Co", "120.75"],
  ["0417", "Pinecrest", "18.40"],
] as const;

export function HeroDemo() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const app = ref.current;
    if (!app) return;
    let alive = true;
    const q = <T extends HTMLElement = HTMLElement>(s: string) => app.querySelector<T>(s)!;
    const cursor = q(".cursor"), list = q(".steplist"), rows = [...app.querySelectorAll<HTMLElement>(".r[data-a]")];
    const sleep = (ms: number) =>
      new Promise<void>((res, rej) => setTimeout(() => (alive ? res() : rej(new Error("unmounted"))), ms));
    const point = async (el: HTMLElement) => {
      const a = app.getBoundingClientRect(), b = el.getBoundingClientRect();
      cursor.style.transform = `translate(${b.left - a.left + Math.min(b.width * 0.5, 40)}px, ${b.top - a.top + b.height * 0.55}px)`;
      await sleep(750);
    };
    const press = async (el: HTMLElement) => { el.classList.add("press"); await sleep(160); el.classList.remove("press"); };
    const addStep = ([op, ex, model]: readonly [string, string, string]) => {
      const d = document.createElement("div");
      d.className = model ? "stp ai" : "stp";
      d.append(Object.assign(document.createElement("b"), { textContent: op }), Object.assign(document.createElement("span"), { textContent: ex }));
      if (model) d.append(Object.assign(document.createElement("i"), { textContent: model }));
      list.appendChild(d);
      q(".stepcount").textContent = String(list.children.length);
    };
    const show = (name: "builder" | "airflow") => {
      q(".builder").classList.toggle("hide", name !== "builder");
      q(".airflow").classList.toggle("hide", name !== "airflow");
    };
    const structure = () => { q(".raw").hidden = true; q(".tbl").hidden = false; q(".rowcount").textContent = "6 rows"; };
    const filter = () => { rows.forEach((r) => r.classList.toggle("out", parseFloat(r.dataset.a!) <= 100)); q(".rowcount").textContent = "3 rows"; };
    const reset = () => {
      list.replaceChildren(); q(".stepcount").textContent = "0";
      rows.forEach((r) => r.classList.remove("out")); q(".rowcount").textContent = "6 PDFs";
      q(".raw").hidden = false; q(".tbl").hidden = true; q(".badge").classList.remove("show");
      const bar = q(".newbar"); bar.style.height = "0"; bar.classList.remove("ok"); q(".newsq").className = "newsq";
      const st = q(".afstate"); st.textContent = "queued"; st.className = "afstate"; q(".afrows").textContent = "–";
      q(".crumb").innerHTML = "DTE Pipelines / <b>invoices</b>"; show("builder");
    };

    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      reset(); STEPS.forEach(addStep); structure(); filter();
      q(".badge").classList.add("show"); cursor.hidden = true;
      return () => { alive = false; };
    }

    (async () => {
      for (;;) {
        reset(); await sleep(900);
        const add = q(".add");
        await point(add); await press(add); addStep(STEPS[0]);
        q(".prev").classList.add("busy"); await sleep(1100);
        q(".prev").classList.remove("busy"); structure(); await sleep(1300);
        await point(add); await press(add); addStep(STEPS[1]); await sleep(450);
        filter(); await sleep(1100);
        await point(add); await press(add); addStep(STEPS[2]); await sleep(400);
        q(".badge").classList.add("show"); await sleep(1300);
        const run = q(".runbtn"); await point(run); await press(run);
        show("airflow"); q(".crumb").innerHTML = "Dags / <b>dte__invoices</b>";
        await sleep(500);
        const st = q(".afstate"); st.textContent = "running"; st.className = "afstate run"; q(".newsq").className = "newsq run";
        q(".newbar").style.height = "70%"; await sleep(1500);
        q(".newbar").classList.add("ok"); q(".newsq").className = "newsq ok";
        st.textContent = "success"; st.className = "afstate ok"; q(".afrows").textContent = "3";
        await sleep(3200);
      }
    })().catch(() => {});
    return () => { alive = false; };
  }, []);

  return (
    <div className="app" ref={ref} role="img" aria-label="Animated demo: structuring invoice PDFs into a table in DTE, then Airflow running it">
      <div className="app-top">
        <i /><i /><i />
        <span className="crumb">DTE Pipelines / <b>invoices</b></span>
        <span className="runbtn">▶ Run</span>
      </div>
      <div className="app-main">
        <div className="rail"><span /><span /><span /><span className="on" /></div>
        <div className="screen builder">
          <div className="form">
            <div className="pnl"><span className="lbl">Source</span><div className="fld">documents <em>invoices/*.pdf</em></div></div>
            <div className="pnl">
              <span className="lbl">Steps <b className="stepcount">0</b></span>
              <div className="steplist" />
              <div className="add">+ Add step</div>
            </div>
            <div className="pnl"><span className="lbl">Destination</span><div className="fld">warehouse <em>invoices</em></div></div>
          </div>
          <div className="prev">
            <div className="prev-h"><b>Live preview</b><span className="rowcount">6 PDFs</span></div>
            <div className="grid raw">
              <div className="r hd"><span>file</span><span>text</span></div>
              {ROWS.map(([no, vendor, total]) => (
                <div key={no} className="r"><span>inv_{no}.pdf</span><span>{vendor.toUpperCase()} Invoice INV-{no} … Total ${total}</span></div>
              ))}
            </div>
            <div className="grid tbl" hidden>
              <div className="r hd"><span>invoice_no</span><span>vendor</span><span>total</span></div>
              {ROWS.map(([no, vendor, total]) => (
                <div key={no} className="r" data-a={total}><span>INV-{no}</span><span>{vendor}</span><span>{total}</span></div>
              ))}
            </div>
            <div className="badge">✓ check passed · 3 / 3</div>
          </div>
        </div>
        <div className="screen airflow hide">
          <div className="af-h"><span className="af-k">Dag</span><b>dte__invoices</b></div>
          <div className="af-meta">
            <div><span className="af-k">Schedule</span>0 6 * * *</div>
            <div><span className="af-k">Latest run</span><span className="afstate">queued</span></div>
            <div><span className="af-k">Rows written</span><span className="afrows">–</span></div>
          </div>
          <div className="af-grid">
            <div className="bars"><i style={{ height: "55%" }} /><i style={{ height: "80%" }} /><i style={{ height: "62%" }} /><i className="newbar" style={{ height: 0 }} /></div>
            <div className="task"><span>run</span><span className="sqs"><b className="ok" /><b className="ok" /><b className="ok" /><b className="newsq" /></span></div>
          </div>
        </div>
      </div>
      <div className="cursor" aria-hidden="true" />
    </div>
  );
}
