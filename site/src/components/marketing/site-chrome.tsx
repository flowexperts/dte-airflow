import Link from "next/link";
import { DOCS_URL, REPO_URL } from "@/lib/site";

/** Nav + footer, shared by the landing page and the use-case pages so the two
 *  surfaces can't drift. Plain markup — no state, no client boundary. */

export function TopNav() {
  return (
    <nav className="top">
      <div className="wrap">
        <Link href="/" className="brand" aria-label="dte">
          dt<span className="e">e</span>
        </Link>
        <div className="nav-right">
          <a href={DOCS_URL} className="btn ghost">Docs</a>
          <a href={REPO_URL} className="btn ghost">GitHub</a>
          <Link href="/#quickstart" className="btn primary">Quickstart</Link>
        </div>
      </div>
    </nav>
  );
}

export function SiteFooter() {
  return (
    <footer>
      <div className="wrap">
        <div className="foot-left">
          <Link href="/" className="brand brand-sm">
            dt<span className="e">e</span>
          </Link>
          <span className="copy">data transformation engine for Apache Airflow · Apache-2.0</span>
        </div>
        <div className="right">
          <a href={REPO_URL}>GitHub</a>
          <a href={DOCS_URL}>Docs</a>
          <Link href="/#book">Production help</Link>
          <span className="copy">© {new Date().getFullYear()}</span>
        </div>
      </div>
      <div className="wrap">
        <span className="copy">
          Apache Airflow, Airflow and the Airflow logo are trademarks of the Apache Software
          Foundation. DTE is an independent project, not affiliated with or endorsed by the ASF.
        </span>
      </div>
    </footer>
  );
}
