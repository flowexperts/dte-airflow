import useSWR from "swr";
import { InlineError, PageHeader, Topbar } from "@/components/ui";
import { listSources, type Source } from "@/lib/api";
import { SourcesTable } from "@/components/sources-table";
import { NewResourceButton } from "@/components/new-resource-button";
import { humanizeError } from "@/lib/errors";

export default function SourcesPage() {
  const { data, error } = useSWR<Source[]>("sources", () => listSources());
  const rows = data ?? [];
  const err = error ? humanizeError(error, { action: "load", entity: "sources" }) : null;

  return (
    <>
      <Topbar
        crumbs={[{ label: "Admin" }, { label: "Sources" }]}
        actions={<NewResourceButton perm="source:write" href="/sources/new" label="New source" />}
      />
      <PageHeader
        title="Sources"
        sub={`${rows.length} total`}
        lede="Reusable data source definitions. Pipelines reference them by id."
      />

      <div className="px-14 py-8">
        {err ? (
          <InlineError title={err.title} message={err.message} detail={err.detail} />
        ) : (
          <SourcesTable rows={rows} />
        )}
      </div>
    </>
  );
}
