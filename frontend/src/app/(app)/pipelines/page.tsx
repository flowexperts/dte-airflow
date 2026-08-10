import { InlineError, PageHeader, Topbar } from "@/components/ui";
import { listPipelines, type Pipeline } from "@/lib/api";
import { PipelinesTable } from "@/components/pipelines-table";
import { NewResourceButton } from "@/components/new-resource-button";
import { humanizeError, type HumanError } from "@/lib/errors";

export const revalidate = 30; // list/detail shell — SWR handles freshness client-side (P2 #26)

/**
 * One list, no `?type=` split.
 *
 * Transform and Quality were two nav entries pointing at the same page with a
 * filter applied, which made a *filter* look like two different places. The
 * table already carries a Type tag per row and its search box matches type, so
 * "just the quality ones" is a keystroke rather than a separate destination —
 * and the common question, "what pipelines do I have", stops being split
 * across two screens neither of which answers it.
 */
export default async function PipelinesPage() {
  let pipelines: Pipeline[] = [];
  let error: HumanError | null = null;
  try {
    pipelines = await listPipelines();
  } catch (e) {
    error = humanizeError(e, { action: "load", entity: "pipelines" });
  }

  const title = "Pipelines";
  const lede =
    "Batch transformations and quality checks. Click a row to open it; filter by name, id, or type.";

  return (
    <>
      <Topbar
        crumbs={[{ label: "Workspace", href: "/" }, { label: title }]}
        actions={
          <NewResourceButton perm="pipeline:write" href="/pipelines/new" label="New pipeline" />
        }
      />
      <PageHeader
        title={title}
        sub={`${pipelines.length} total`}
        lede={lede}
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
