import { notFound } from "next/navigation";
import {
  ApiError,
  getDestination,
  getPipeline,
  getSource,
  type Destination,
  type Source,
} from "@/lib/api";
import { asVariant } from "../../_variant";
import { LabPipelineDetail } from "./_detail";

export const dynamic = "force-dynamic";

type Params = Promise<{ id: string }>;
type SearchParams = Promise<{ v?: string; edit?: string }>;

export default async function LabPipelineDetailPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: SearchParams;
}) {
  const { id } = await params;
  const { v, edit } = await searchParams;
  const variant = asVariant(v, ["a", "b", "c"]);

  try {
    const pipeline = await getPipeline(id);
    const [sources, destination] = await Promise.all([
      Promise.all(
        (pipeline.sources ?? []).map((sid) =>
          getSource(sid).catch(() => null as Source | null),
        ),
      ),
      pipeline.output_id
        ? getDestination(pipeline.output_id).catch(() => null as Destination | null)
        : Promise.resolve(null),
    ]);

    return (
      <LabPipelineDetail
        initialPipeline={pipeline}
        sources={sources}
        destination={destination}
        variant={variant}
        initialEdit={edit === "1"}
      />
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}
