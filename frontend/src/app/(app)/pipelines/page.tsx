import { InlineError, PageHeader, Topbar } from "@/components/ui";
import { listPipelines, type Pipeline } from "@/lib/api";
import { PipelinesTable } from "@/components/pipelines-table";
import { NewResourceButton } from "@/components/new-resource-button";
import { humanizeError, type HumanError } from "@/lib/errors";

export const revalidate = 30; // list/detail shell — SWR handles freshness client-side (P2 #26)

export default async function PipelinesPage() {
  let pipelines: Pipeline[] = [];
  let error: HumanError | null = null;
  try {
    pipelines = await listPipelines();
  } catch (e) {
    error = humanizeError(e, { action: "load", entity: "pipelines" });
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
          <InlineError title={error.title} message={error.message} detail={error.detail} />
        ) : (
          <PipelinesTable rows={pipelines} />
        )}
      </div>
    </>
  );
}
