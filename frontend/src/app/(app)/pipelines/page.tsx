import { PageHeader, Topbar } from "@/components/ui";
import { listPipelines, type Pipeline } from "@/lib/api";
import { PipelinesTable } from "@/components/pipelines-table";
import { NewResourceButton } from "@/components/new-resource-button";

export const revalidate = 30; // list/detail shell — SWR handles freshness client-side (P2 #26)

export default async function PipelinesPage() {
  let pipelines: Pipeline[] = [];
  let error: string | null = null;
  try {
    pipelines = await listPipelines();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <>
      <Topbar
        crumbs={[{ label: "Workspace", href: "/" }, { label: "Pipelines" }]}
        actions={
          <NewResourceButton perm="pipeline:write" href="/pipelines/new" label="New pipeline" />
        }
      />
      <PageHeader
        title="Pipelines"
        sub={`${pipelines.length} total`}
        lede="Batch data transformations. Click a row to open its builder or run history."
      />

      <div className="px-14 py-8">
        {error ? (
          <div className="p-4 border border-red rounded bg-code-bg text-red font-mono text-sm">
            Backend unreachable: {error}
          </div>
        ) : (
          <PipelinesTable rows={pipelines} />
        )}
      </div>
    </>
  );
}
