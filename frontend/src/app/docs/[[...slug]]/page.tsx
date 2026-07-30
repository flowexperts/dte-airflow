import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { getDoc, listDocs } from "@/lib/docs";

export const dynamic = "force-static";
export const dynamicParams = false;

export async function generateStaticParams() {
  const entries = await listDocs();
  // Root index page is `slug: undefined` — Next.js catches it via the optional catch-all.
  return entries.map((e) => ({ slug: e.slug.length ? e.slug : undefined }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug?: string[] }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const doc = await getDoc(slug ?? []);
  if (!doc) return { title: "Docs · dte" };
  return { title: `${doc.title} · dte docs` };
}

export default async function DocPage({
  params,
}: {
  params: Promise<{ slug?: string[] }>;
}) {
  const { slug } = await params;
  const doc = await getDoc(slug ?? []);
  if (!doc) notFound();

  return (
    <article className="docs-article">
      <div className="docs-prose" dangerouslySetInnerHTML={{ __html: doc.html }} />
      <footer className="docs-footer">
        <a
          href={`https://github.com/bhavaniravi/dte/blob/main/docs/user/${doc.relPath}`}
          target="_blank"
          rel="noreferrer"
        >
          Edit on GitHub
        </a>
      </footer>
    </article>
  );
}
