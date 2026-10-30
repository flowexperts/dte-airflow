import Link from "next/link";
import { USE_CASES, type UseCase } from "@/lib/use-cases";
import { InstallBox, SiteFooter, TopNav } from "./site-chrome";
import { PageHero } from "./page-hero";
import { PipelineCard } from "./pipeline-card";

export function UseCasePage({ uc }: { uc: UseCase }) {
  const others = USE_CASES.filter((u) => u.slug !== uc.slug);
  return (
    <div className="site">
      <TopNav current="use-cases" />
      <main>
        <PageHero title={uc.headline} hi="" lede={uc.lede} />
        <section className="s"><div className="in">
          <p className="kicker">{uc.dept}</p>
          <h2>The pipeline</h2>
          <div className="split">
            <div className="copy">
              <span className="who">Today</span>
              <ul>{uc.pains.map((p) => <li key={p}><div><b>{p}</b></div></li>)}</ul>
            </div>
            <div className="vis"><PipelineCard steps={uc.steps} /></div>
          </div>
        </div></section>

        <section className="s"><div className="in">
          <p className="kicker">With DTE</p>
          <h2>What you get instead</h2>
          <div className="outcomes">
            {uc.outcomes.map((o) => (
              <div key={o.label} className="card"><h3>{o.label}</h3><p>{o.hint}</p></div>
            ))}
          </div>
        </div></section>

        <section className="s"><div className="in">
          <p className="kicker">Other teams</p>
          <h2>Same engine, different paperwork</h2>
          <div className="outcomes">
            {others.map((u) => (
              <Link key={u.slug} href={`/use-cases/${u.slug}/`} className="card">
                <span className="who">{u.dept}</span><h3>{u.headline}</h3>
              </Link>
            ))}
          </div>
        </div></section>

        <section className="s" id="install"><div className="in"><InstallBox /></div></section>
      </main>
      <SiteFooter />
    </div>
  );
}
