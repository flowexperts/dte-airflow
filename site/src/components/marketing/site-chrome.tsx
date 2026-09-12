import Link from "next/link";

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
          <Link href="/#use-cases" className="btn ghost">Usecases</Link>
          <Link href="/#book" className="btn primary">Request access</Link>
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
          <span className="copy">data transformation engine · map once, run anytime</span>
        </div>
        <div className="right">
          <Link href="/#book">Request access</Link>
          <span className="copy">© {new Date().getFullYear()}</span>
        </div>
      </div>
    </footer>
  );
}
