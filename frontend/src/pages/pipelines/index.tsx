import { useRouter, useSearchParams } from "@/lib/nav";
import useSWR from "swr";
import { InlineError, PageHeader, Segmented, Topbar } from "@/components/ui";
import { listPipelines, type Pipeline } from "@/lib/api";
import { PipelinesTable } from "@/components/pipelines-table";
import { NewResourceButton } from "@/components/new-resource-button";
import { withSuspense } from "@/components/with-suspense";
import { humanizeError } from "@/lib/errors";
import {
  PIPELINE_TYPE_TABS,
  parsePipelineType,
  pipelineListCopy,
  type PipelineTypeFilter,
} from "@/lib/pipeline-type";

function PipelinesPage() {
  const router = useRouter();
  // No ?type= means Transform: the unfiltered list would surface the hidden
  // Eval and Visualize pipelines (plan 067).
  const pipelineType =
    parsePipelineType(useSearchParams().get("type") ?? undefined) ?? "transform";
  const { data, error } = useSWR<Pipeline[]>("pipelines", () => listPipelines());
  const pipelines = (data ?? []).filter(
    (p) => !pipelineType || (p.pipeline_type ?? "transform") === pipelineType,
  );
  const err = error ? humanizeError(error, { action: "load", entity: "pipelines" }) : null;
  const { title, lede } = pipelineListCopy(pipelineType);

  return (
    <>
      <Topbar
        crumbs={[{ label: "DTE Pipelines", href: "/pipelines" }, { label: title }]}
        actions={
          <NewResourceButton perm="pipeline:write" href="/pipelines/new" label="New pipeline" />
        }
      />
      <PageHeader title={title} sub={`${pipelines.length} total`} lede={lede} />

      <div className="px-14 py-8 space-y-4">
        {/* The pipeline types, formerly DTE's sidebar links. */}
        <Segmented<PipelineTypeFilter>
          options={PIPELINE_TYPE_TABS.map(({ type, label }) => ({ value: type, label }))}
          value={pipelineType}
          onChange={(t) => router.replace(`/pipelines?type=${t}`)}
        />
        {err ? (
          <InlineError title={err.title} message={err.message} detail={err.detail} />
        ) : (
          <PipelinesTable rows={pipelines} />
        )}
      </div>
    </>
  );
}

export default withSuspense(PipelinesPage);
