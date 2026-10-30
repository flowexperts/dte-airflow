import type { Metadata } from "next";
import { InstallBox, SiteFooter, TopNav } from "@/components/marketing/site-chrome";
import { PageHero } from "@/components/marketing/page-hero";
import { OssList } from "@/components/marketing/oss-list";
import { OSS_GROUPS } from "@/lib/oss";
import { REPO_URL, pageMeta } from "@/lib/site";

const LEDE =
  "DTE is a thin layer over projects other people built and maintain. Here is each one, what DTE uses it for, and its license.";

export const metadata: Metadata = pageMeta("Built on open source", LEDE, "/open-source/");

export default function Page() {
  return (
    <div className="site">
      <TopNav />
      <main>
        <PageHero title="Built on" hi="open source" lede={LEDE} />
        <section className="s"><div className="in">
          {OSS_GROUPS.map((g) => (
            <div key={g.title}>
              <h2 className="oss-group">{g.title}</h2>
              <OssList items={g.items} />
            </div>
          ))}
          <p className="oss-more">
            The full dependency list, with versions, is in the repo:{" "}
            <a href={`${REPO_URL}/blob/main/backend/pyproject.toml`}>backend</a>,{" "}
            <a href={`${REPO_URL}/blob/main/frontend/package.json`}>UI</a>. DTE itself is Apache-2.0.
          </p>
        </div></section>
        <section className="s" id="install"><div className="in"><InstallBox /></div></section>
      </main>
      <SiteFooter />
    </div>
  );
}
