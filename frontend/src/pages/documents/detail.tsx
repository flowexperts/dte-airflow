import { useSearchParams } from "@/lib/nav";
import { PageHeader, Topbar } from "@/components/ui";
import { DocumentInspector } from "@/components/document-inspector/DocumentInspector";
import { MissingParam } from "@/components/missing-param";
import { withSuspense } from "@/components/with-suspense";

/**
 * Deep link to one stored document (`?key=<artifact key>`).
 *
 * Field provenance is not available here: it lives on the *row*, not on the
 * document. Opening the inspector from a run's output table carries the row
 * along and does show the highlights; this route is for the source document.
 */
function DocumentPage() {
  const q = useSearchParams();
  const key = q.get("key");
  if (!key) return <MissingParam what="document" />;
  const page = Number(q.get("page")) || 1;
  const name = q.get("name");

  return (
    <>
      <Topbar crumbs={[{ label: "DTE Pipelines", href: "/pipelines" }, { label: "Document" }]} />
      <PageHeader
        title={name || "Document"}
        sub={`artifact ${key.slice(0, 12)}…`}
        lede="The source document behind an extracted row."
      />
      <div className="px-14 py-8">
        <DocumentInspector
          docKey={key}
          extractKey={q.get("extract")}
          initialPage={page}
          filename={name}
        />
      </div>
    </>
  );
}

export default withSuspense(DocumentPage);
