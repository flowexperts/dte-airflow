import { InlineError, PageHeader, Topbar } from "@/components/ui";
import { listSources, type Source } from "@/lib/api";
import { SourcesTable } from "@/components/sources-table";
import { NewResourceButton } from "@/components/new-resource-button";
import { humanizeError, type HumanError } from "@/lib/errors";

export const revalidate = 30; // list/detail shell — SWR handles freshness client-side (P2 #26)

export default async function SourcesPage() {
  let sources: Source[] = [];
  let error: HumanError | null = null;
  try {
    sources = await listSources();
  } catch (e) {
    error = humanizeError(e, { action: "load", entity: "sources" });
  }

  return (
    <>
      <Topbar
        crumbs={[{ label: "Workspace", href: "/" }, { label: "Sources" }]}
        actions={
          <NewResourceButton perm="source:write" href="/sources/new" label="New source" />
        }
      />
      <PageHeader
        title="Sources"
        sub={`${sources.length} total`}
        lede="Reusable data source definitions. Pipelines reference them by id."
      />

      <div className="px-14 py-8">
        {error ? (
          <InlineError title={error.title} message={error.message} detail={error.detail} />
        ) : (
          <SourcesTable rows={sources} />
        )}
      </div>
    </>
  );
}
