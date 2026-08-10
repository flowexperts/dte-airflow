import { notFound } from "next/navigation";
import {
  ApiError,
  getDestination,
  getPipeline,
  getSource,
  type Destination,
  type Source,
} from "@/lib/api";
import { orNull } from "@/lib/errors";
import { PipelineCanvas } from "@/components/pipeline/canvas";

export const dynamic = "force-dynamic";

type Params = Promise<{ id: string }>;

export default async function PipelineDetail({ params }: { params: Params }) {
  const { id } = await params;

  try {
    const pipeline = await getPipeline(id);
    // A missing source or destination is a state the page must render, not an
    // error — the canvas shows it as "not found" so it can be fixed in place.
    const [sources, destination] = await Promise.all([
      Promise.all(
        (pipeline.sources ?? []).map((sid) =>
          getSource(sid).catch(orNull<Source>),
        ),
      ),
      pipeline.output_id
        ? getDestination(pipeline.output_id).catch(orNull<Destination>)
        : Promise.resolve(null),
    ]);

    return (
      <PipelineCanvas
        initialPipeline={pipeline}
        sources={sources}
        destination={destination}
      />
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}
