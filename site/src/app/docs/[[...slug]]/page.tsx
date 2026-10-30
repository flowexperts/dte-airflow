import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { SiteFooter, TopNav } from "@/components/marketing/site-chrome";
import { allSlugs, getDoc, hrefFor, navTitles } from "@/lib/docs";
import { REPO_URL } from "@/lib/site";
import "./docs.css";

export const dynamicParams = false;

type Params = Promise<{ slug?: string[] }>;
const slugOf = async (params: Params) => ((await params).slug ?? []).join("/");

export function generateStaticParams() {
  return allSlugs().map((s) => ({ slug: s ? s.split("/") : [] }));
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const doc = getDoc(await slugOf(params));
  if (!doc) return {};
  return {
    title: doc.slug ? `${doc.title} · Docs` : "Docs",
    description: doc.description,
    alternates: { canonical: hrefFor(doc.slug) },
  };
}

export default async function DocPage({ params }: { params: Params }) {
  const doc = getDoc(await slugOf(params));
  if (!doc) notFound();
  const source = `${REPO_URL}/blob/main/docs/user/${doc.slug || "README"}.md`;

  return (
    <div className="site docs-page">
      <TopNav />
      <main className="wrap docs-layout">
        <article className="docs-prose">
          <div dangerouslySetInnerHTML={{ __html: doc.html }} />
          <p className="docs-edit">
            <a href={source}>Edit this page on GitHub</a>
          </p>
        </article>
        <nav className="docs-nav" aria-label="Docs">
          {navTitles().map(({ section, items }) => (
            <div key={section} className="docs-nav-group">
              <span className="docs-nav-section">{section}</span>
              {items.map((it) => (
                <Link
                  key={it.slug}
                  href={hrefFor(it.slug)}
                  aria-current={it.slug === doc.slug ? "page" : undefined}
                >
                  {it.title}
                </Link>
              ))}
            </div>
          ))}
        </nav>
      </main>
      <SiteFooter />
    </div>
  );
}
