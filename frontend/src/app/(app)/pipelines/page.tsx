import { InlineError, PageHeader, Topbar } from "@/components/ui";
import { listPipelines, type Pipeline } from "@/lib/api";
import { PipelinesTable } from "@/components/pipelines-table";
import { NewResourceButton } from "@/components/new-resource-button";
import { humanizeError, type HumanError } from "@/lib/errors";

export const revalidate = 30; // list/detail shell — SWR handles freshness client-side (P2 #26)

type SearchParams = Promise<{ type?: string }>;

export default async function PipelinesPage({ searchParams }: { searchParams: SearchParams }) {
  const { type } = await searchParams;
  const pipelineType = type === "quality" ? "quality" : type === "transform" ? "transform" : null;

  let pipelines: Pipeline[] = [];
  let error: HumanError | null = null;
  try {
    const all = await listPipelines();
    pipelines = pipelineType
      ? all.filter((p) => (p.pipeline_type ?? "transform") === pipelineType)
      : all;
  } catch (e) {
    error = humanizeError(e, { action: "load", entity: "pipelines" });
  }

  const title =
    pipelineType === "quality"
      ? "Quality pipelines"
      : pipelineType === "transform"
        ? "Transform pipelines"
        : "Pipelines";

  const lede =
    pipelineType === "quality"
      ? "Data quality checks. Each run asserts conditions and reports pass/fail results."
      : "Batch data transformations. Click a row to open its builder or run history.";

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
