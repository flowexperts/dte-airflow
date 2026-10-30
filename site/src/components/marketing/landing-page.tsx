import { HeroDemo } from "./hero-demo";
import { InstallBox, SiteFooter, TopNav } from "./site-chrome";
import { INSTALL_URL } from "@/lib/site";

const FAQ = [
  ["Is it ready for production?", <>It&apos;s in beta. Interfaces and the <code>dte</code> schema can still change between releases, so back up before you upgrade.</>],
  ["Do I need to run another service?", <>No. DTE is an Airflow plugin. It runs in your api-server and scheduler and keeps its tables in a <code>dte</code> schema in Postgres.</>],
  ["Does our data leave our network?", <>No. It runs in your Airflow, on your connections. PDF extraction calls the model provider you configure, or a regex provider when nothing may leave.</>],
  ["Where does it sit next to dbt?", <>dbt models data that&apos;s already in your warehouse. DTE gets it there: files, APIs and PDFs, mapped and checked on the way in.</>],
  ["What does it cost?", <>Nothing. It&apos;s Apache-2.0. If you&apos;d like help deploying it, you can book time with me.</>],
] as const;

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
              <h1>Visual pipeline builder <span className="hi">for Apache Airflow</span></h1>
              <p className="lede">
                Stop hand-writing mapping DAGs. The people who know the data build the pipeline in
                the browser, from files, tables or even PDFs. Each one runs as a DAG in the Airflow
                you already have.
              </p>
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
          <h2>Watch one go from ticket to DAG</h2>
          <ol className="how">
            <li><b>Install it into Airflow</b><span>One pip install into Airflow 3.3+, with Airflow&apos;s own constraints file. There&apos;s no new service to run.</span></li>
            <li><b>Hand over the mapping</b><span>Finance, ops or whoever owns the data builds the pipeline in the browser and previews real rows before saving.</span></li>
            <li><b>Airflow runs it</b><span>Each pipeline is a <code>dte__</code> DAG. Schedules, retries, alerts and run history work the way they already do.</span></li>
          </ol>
          <video className="video" controls muted playsInline preload="metadata" poster="/demo/dte-airflow-poster.jpg">
            <source src="/demo/dte-airflow.mp4" type="video/mp4" />
            <source src="/demo/dte-airflow.webm" type="video/webm" />
          </video>
        </div></section>

        <section className="s" id="install"><div className="in">
          <InstallBox />
        </div></section>
        <section className="s" id="faq"><div className="in">
          <h2>FAQ</h2>
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
