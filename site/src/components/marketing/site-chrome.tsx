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
        <Link href="/" className="logo" aria-label="dte home">dt<span className="e">e</span></Link>
        <span className="sp" />
        <span className="links">
          <Link className="hide" href="/use-cases/" {...here("use-cases")}>Use cases</Link>
          <Link className="hide" href="/integrations/" {...here("integrations")}>Integrations</Link>
          <a href={DOCS_URL}>Docs</a>
        </span>
        <a className="gh" href={REPO_URL} aria-label="GitHub">
          <svg viewBox="0 0 16 16" width="20" height="20" aria-hidden="true" fill="currentColor">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
          </svg>
        </a>
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
          <Link href="/" className="logo">dt<span className="e">e</span></Link>
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
            <li><Link href="/open-source/">Built on open source</Link></li>
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
