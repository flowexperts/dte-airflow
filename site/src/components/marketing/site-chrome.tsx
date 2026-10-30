import Link from "next/link";
import { DOCS_URL, INSTALL_URL, REPO_URL } from "@/lib/site";
import "./site.css";

/** Nav, install box and footer, shared by every marketing page so they
 *  can't drift. Plain markup — no state, no client boundary. */

export const CAL_LINK = "bhavaniravi/dte-demo-call";

// Install into an existing Airflow 3.3+, with Airflow's constraints unmodified.
const QUICKSTART = [
  "curl -fsSLo constraints.txt https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt",
  "pip install dte-airflow --constraint constraints.txt",
  "export DTE_DATABASE_URL=postgresql://user:pass@host/dte",
  "dte db upgrade",
];

export function TopNav({ current }: { current?: "use-cases" | "integrations" }) {
  const here = (k: string) => (current === k ? { "aria-current": "page" as const } : {});
  return (
    <nav className="nav">
      <div className="in">
        <Link href="/" className="logo" aria-label="dte home"><i />dte</Link>
        <span className="links">
          <Link className="hide" href="/use-cases/" {...here("use-cases")}>Use cases</Link>
          <Link className="hide" href="/integrations/" {...here("integrations")}>Integrations</Link>
          <a href={DOCS_URL}>Docs</a>
        </span>
        <span className="sp" />
        <a className="hide-sm" href={REPO_URL}>GitHub</a>
        <Link className="btn go" href="/#install">Install</Link>
      </div>
    </nav>
  );
}

export function InstallBox() {
  return (
    <div className="help">
      <h3>Try it on your Airflow</h3>
      <div className="term small">
        {QUICKSTART.map((line) => (
          <div key={line}><span className="p">$</span> {line}</div>
        ))}
      </div>
      <p>
        Restart Airflow and find DTE under <b>Plugins ▸ DTE Pipelines</b>. Airflow 3.3+, beta,
        Apache-2.0.
      </p>
      <a className="btn go" href={INSTALL_URL}>Install DTE in your Airflow</a>
      <a className="plain" href={`https://cal.com/${CAL_LINK}`} target="_blank" rel="noopener noreferrer">
        or book 30 minutes with me
      </a>
    </div>
  );
}

export function SiteFooter() {
  return (
    <footer>
      <div className="in">
        <div>
          <Link href="/" className="logo"><i style={{ background: "var(--paper)" }} />dte</Link>
          <p className="pw">Built and maintained by <b>flowexperts.ai</b></p>
        </div>
        <div>
          <h4>Product</h4>
          <ul>
            <li><a href={DOCS_URL}>Docs</a></li>
            <li><a href={INSTALL_URL}>Install</a></li>
            <li><Link href="/use-cases/">Use cases</Link></li>
            <li><Link href="/integrations/">Integrations</Link></li>
          </ul>
        </div>
        <div>
          <h4>Project</h4>
          <ul>
            <li><a href={REPO_URL}>GitHub</a></li>
            <li><a href={`${REPO_URL}/issues`}>Issues</a></li>
          </ul>
        </div>
        <div>
          <h4>Company</h4>
          <ul>
            <li><a href="https://flowexperts.ai">flowexperts.ai</a></li>
            <li><a href={`https://cal.com/${CAL_LINK}`}>Book a call</a></li>
          </ul>
        </div>
        <div className="fine">
          Apache-2.0. Apache Airflow, Airflow and the Airflow logo are trademarks of the Apache
          Software Foundation. DTE is an independent project, not affiliated with or endorsed by the
          ASF.
        </div>
      </div>
    </footer>
  );
}
