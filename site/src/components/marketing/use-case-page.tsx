import Link from "next/link";
import { UseCaseCards } from "./use-case-cards";
import { type UseCase } from "@/lib/use-cases";
import { SiteFooter, TopNav } from "./site-chrome";
import "./landing.css";

export function UseCasePage({ uc }: { uc: UseCase }) {
  return (
    <div className="mkt-root uc-page" data-theme="dark">
      <TopNav />

      <main>
        <section className="hero uc-hero">
          <div className="wrap">
            <span className="eyebrow">{uc.dept}</span>
            <h1 className="h-gap-lg">{uc.headline}</h1>
            <p className="lede">{uc.lede}</p>
            <div className="hero-ctas">
              <Link href="/#quickstart" className="btn primary">
                Quickstart <span className="kbd">↵</span>
              </Link>
              <Link href="/#demo" className="btn ghost">See the builder</Link>
            </div>
          </div>
        </section>

        <section className="steps-section">
          <div className="wrap">
            <div className="uc-grid">
              <div>
                <span className="section-eyebrow">Today</span>
                <h2 className="h-gap-md">What this costs you now.</h2>
                <div className="qa-rows">
                  {uc.pains.map((p, i) => (
                    <div key={p} className="qa-row">
                      <div className="qa-glyph">{String(i + 1).padStart(2, "0")}</div>
                      <div>
                        <span className="qa-row-hint">{p}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="logic-panel" aria-label="pipeline">
                <div className="logic-head">
                  <span className="dots"><i /><i /><i /></span>
                  {uc.slug.replace(/-/g, "_")}_pipeline
                </div>
                <div className="logic-steps">
                  {uc.steps.map((s, i) => (
                    <div key={s.op + s.expr} className="lstep">
                      <span className="idx">{String(i + 1).padStart(2, "0")}</span>
                      <span className="op">{s.op}</span>
                      <span className="expr">{s.expr}</span>
                    </div>
                  ))}
                </div>
                <div className="logic-foot">
                  <span className="pill ok"><span className="dotp" />preview ok</span>
                  <span>runs on your schedule</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="steps-section">
          <div className="wrap">
            <div className="section-head">
              <div className="section-head-copy">
                <span className="section-eyebrow">With DTE</span>
                <h2>What you get instead.</h2>
              </div>
            </div>
            <div className="steps-grid">
              {uc.outcomes.map((o) => (
                <div key={o.label} className="steps-card">
                  <span className="steps-card-label">{o.label}</span>
                  <span className="steps-card-hint">{o.hint}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="steps-section">
          <div className="wrap">
            <div className="section-head">
              <div className="section-head-copy">
                <span className="section-eyebrow">Other teams</span>
                <h2>Same engine, different paperwork.</h2>
              </div>
            </div>
            <UseCaseCards exclude={uc.slug} />
          </div>
        </section>

        <section className="book">
          <div className="wrap">
            <div className="book-copy">
              <span className="section-eyebrow">Production help</span>
              <h2 className="h-gap-md">See this pipeline on your own files.</h2>
              <ul className="bullets">
                <li>No sales pitch. Zero slides.</li>
              </ul>
              <div className="hero-ctas">
                <Link href="/#book" className="btn primary">Book a 30-min slot</Link>
              </div>
            </div>
          </div>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
