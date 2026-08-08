import { InlineError, PageHeader, Topbar } from "@/components/ui";
import { listPipelines, type Pipeline } from "@/lib/api";
import { humanizeError, type HumanError } from "@/lib/errors";
import { VariantBar } from "../_variant";
import { asVariant, type VariantOption } from "../_variant-util";
import { LabHealthTable } from "./_health-table";
import { LabPipelineCards } from "./_cards";

export const dynamic = "force-dynamic";

type SearchParams = Promise<{ v?: string; type?: string }>;

const OPTIONS: VariantOption[] = [
  {
    value: "a" as const,
    label: "Health table",
    note: "Last run, trend, and shape at the row — no drill-down to answer “is it ok?”",
  },
  {
    value: "b" as const,
    label: "Cards",
    note: "Transform and quality as peer sections, verdict on the card face.",
  },
];

export default async function LabPipelinesPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const { v, type } = await searchParams;
  const variant = asVariant(v, ["a", "b"]);
  const pipelineType =
    type === "quality" ? "quality" : type === "transform" ? "transform" : null;

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

  return (
    <>
      <Topbar
        crumbs={[
          { label: "Workspace", href: "/" },
          { label: "Lab", href: "/lab" },
          { label: "Pipelines" },
        ]}
      />
      <PageHeader
        title="Pipelines"
        sub={`${pipelines.length} total`}
        lede="Transform and quality pipelines together — health is on the row, not behind a click."
      />
      <VariantBar options={OPTIONS} current={variant} />

      <div className="px-14 py-8">
        {error ? (
          <InlineError
            title={error.title}
            message={error.message}
            detail={error.detail}
          />
        ) : variant === "a" ? (
          <LabHealthTable rows={pipelines} />
        ) : (
          <LabPipelineCards rows={pipelines} />
        )}
      </div>
    </>
  );
}
