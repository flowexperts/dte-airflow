import { isValidElement, type ReactNode } from "react";
import { DemoVideo } from "./demo-video";
import { HeroDemo } from "./hero-demo";
import { CAL_LINK, InstallBox, SiteFooter, TopNav } from "./site-chrome";
import { INSTALL_URL, REPO_URL } from "@/lib/site";

const FAQ = [
  ["Is it ready for production?", <>It&apos;s in beta. Interfaces and the <code>dte</code> schema can still change between releases, so back up before you upgrade.</>],
  ["Do I need to run another service?", <>No. DTE is an Airflow plugin. It runs in your api-server and scheduler and keeps its tables in a <code>dte</code> schema in Postgres.</>],
  ["Does our data leave our network?", <>No. It runs in your Airflow, on your connections. PDF extraction calls the model provider you configure, or a regex provider when nothing may leave.</>],
  ["Where does it sit next to dbt?", <>dbt models data that&apos;s already in your warehouse. DTE gets it there: files, APIs and PDFs, mapped and checked on the way in.</>],
  ["What does it cost?", <>Nothing. DTE is open source under Apache-2.0, and the code is on <a href={REPO_URL}>GitHub</a>. If you want help running it, or Airflow itself, in production, that&apos;s what flowexperts.ai does.</>],
] as const;

/** Plain text of an FAQ answer, for the FAQPage JSON-LD. */
function text(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(text).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return text(node.props.children);
  return "";
}

const faqJsonLd = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: FAQ.map(([q, a]) => ({
    "@type": "Question",
    name: q,
    acceptedAnswer: { "@type": "Answer", text: text(a) },
  })),
};

export function LandingPage() {
  return (
    <div className="site">
      <TopNav />
      <main>
        <header className="hero">
          <div className="glyph" aria-hidden="true" />
          <div className="in">
            <div>
              <p className="kicker">Data transformation engine</p>
              <h1>Visual Builder <span className="hi">for Data &amp; AI pipelines</span></h1>
              <p className="powered">Apache Airflow<sup>®</sup> plugin · 100% Open-Source</p>
              <div className="ctas">
                <a className="btn go" href={INSTALL_URL}>Install DTE in your Airflow</a>
                <a className="btn ghost" href="#demo">Watch the demo</a>
              </div>
            </div>
            <HeroDemo />
          </div>
        </header>

        <section className="s"><div className="in">
          <p className="kicker">From the founder</p>
          <h2>Why I built DTE</h2>
          <div className="founder">
            <p>
              At FlowExperts I help teams run Airflow, and the same ticket kept coming back: a new
              file, slightly different from the last, that needed another DAG. The engineer was
              always the bottleneck, and the person who understood the data never got to touch the
              pipeline.
            </p>
            <p>
              DTE is how I&apos;d want that to work. Install it, hand the mapping to the person who
              knows the data, and tell me what breaks.
            </p>
            <p className="sig">Bhavani Ravi, flowexperts.ai</p>
          </div>
        </div></section>

        <section className="s" id="demo"><div className="in">
          <p className="kicker">The demo</p>
          <h2>UI based Rule-Engine</h2>
          <ol className="how">
            <li><b>Install it into Airflow</b><span>One pip install into Airflow 3.3+, with Airflow&apos;s own constraints file. There&apos;s no new service to run.</span></li>
            <li><b>Hand over the mapping</b><span>Finance, ops or whoever owns the data builds the pipeline in the browser and previews real rows before saving.</span></li>
            <li><b>Airflow runs it</b><span>Each pipeline is a <code>dte__</code> DAG. Schedules, retries, alerts and run history work the way they already do.</span></li>
          </ol>
          <DemoVideo />
        </div></section>

        <section className="s" id="install"><div className="in">
          <InstallBox />
        </div></section>

        <section className="s" id="production"><div className="in">
          <p className="kicker">Open source, with backup</p>
          <h2>Airflow in production is the hard part</h2>
          <div className="founder">
            <p>
              DTE is free and open source, and it always will be. Installing it takes a minute.
              Running Airflow well (upgrades, scaling the scheduler, deployments, the 3am failed
              DAG) is the work I do every day at flowexperts.ai.
            </p>
            <p>
              If your team wants DTE and the Airflow under it running in production without
              becoming the bottleneck, talk to us.
            </p>
            <p>
              <a className="btn go" href={`https://cal.com/${CAL_LINK}`} target="_blank" rel="noopener noreferrer">Talk about your Airflow</a>{" "}
              <a className="plain" href="https://flowexperts.ai">or see flowexperts.ai</a>
            </p>
          </div>
        </div></section>
        <section className="s" id="faq"><div className="in">
          <h2>FAQ</h2>
          <script
            type="application/ld+json"
            dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd) }}
          />
          <div className="faq">
            {FAQ.map(([q, a], i) => (
              <details key={q} open={i === 0}><summary>{q}</summary><p>{a}</p></details>
            ))}
          </div>
        </div></section>

      </main>
      <SiteFooter />
    </div>
  );
}
