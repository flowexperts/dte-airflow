import type { Metadata } from "next";
import Link from "next/link";
import { InstallBox, SiteFooter, TopNav } from "@/components/marketing/site-chrome";
import { PageHero } from "@/components/marketing/page-hero";
import { PipelineCard } from "@/components/marketing/pipeline-card";
import { USE_CASES } from "@/lib/use-cases";

const LEDE =
  "Five pipelines, each built in the browser by the team that owns the numbers. Every one ends in a check, so bad data fails the run instead of reaching the report.";

export const metadata: Metadata = {
  title: "Use cases",
  description: LEDE,
  alternates: { canonical: "/use-cases/" },
};

export default function Page() {
  return (
    <div className="site">
      <TopNav current="use-cases" />
      <main>
        <PageHero title="What your teams" hi="will map" lede={LEDE} />
        <section className="s"><div className="in uc">
          {USE_CASES.map((u) => (
            <div key={u.slug} className="split">
              <div className="copy">
                <span className="who">{u.dept}</span>
                <h3><Link href={`/use-cases/${u.slug}/`}>{u.headline}</Link></h3>
                <p>{u.lede}</p>
                <ul>{u.pains.map((p) => <li key={p}><div><b>{p}</b></div></li>)}</ul>
              </div>
              <div className="vis"><PipelineCard steps={u.steps} /></div>
            </div>
          ))}
        </div></section>
        <section className="s" id="install"><div className="in"><InstallBox /></div></section>
      </main>
      <SiteFooter />
    </div>
  );
}
