"use client";

import { use } from "react";
import { PageHeader, Topbar } from "@/components/ui";
import { DocumentInspector } from "@/components/document-inspector/DocumentInspector";

/**
 * Deep link to one stored document.
 *
 * Client-only: pdf.js needs a canvas and a worker, neither of which exists
 * during a server render.
 *
 * Field provenance is not available here. It lives on the *row*, not on the
 * document — the same PDF read by two different `structure` configurations
 * has two different sets of fields — so a URL keyed only by document hash
 * cannot recover it. Opening the inspector from a run's output table carries
 * the row along and does show the highlights; this route is for looking at
 * the source document itself.
 */
export default function DocumentPage({
  params,
  searchParams,
}: {
  params: Promise<{ key: string }>;
  searchParams: Promise<{ extract?: string; page?: string; name?: string }>;
}) {
  const { key } = use(params);
  const q = use(searchParams);
  const page = Number(q.page) || 1;

  return (
    <>
      <Topbar
        crumbs={[
          { label: "Workspace", href: "/" },
          { label: "Document" },
        ]}
      />
      <div className="px-14 py-8">
        <PageHeader
          title={q.name || "Document"}
          sub={`artifact ${key.slice(0, 12)}…`}
          lede="The source document behind an extracted row."
        />
        <div className="mt-6">
          <DocumentInspector
            docKey={key}
            extractKey={q.extract ?? null}
            initialPage={page}
            filename={q.name ?? null}
          />
        </div>
      </div>
    </>
  );
}
