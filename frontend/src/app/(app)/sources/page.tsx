import { PageHeader, Topbar } from "@/components/ui";
import { listSources, type Source } from "@/lib/api";
import { SourcesTable } from "@/components/sources-table";
import { NewResourceButton } from "@/components/new-resource-button";

export const dynamic = "force-dynamic";

export default async function SourcesPage() {
  let sources: Source[] = [];
  let error: string | null = null;
  try {
    sources = await listSources();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
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
          <div className="p-4 border border-red rounded bg-code-bg text-red font-mono text-sm">
            Backend unreachable: {error}
          </div>
        ) : (
          <SourcesTable rows={sources} />
        )}
      </div>
    </>
  );
}
