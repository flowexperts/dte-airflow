import { notFound } from "next/navigation";
import {
  ApiError,
  getDestination,
  getPipelineRevision,
  getSource,
  type Destination,
  type Source,
} from "@/lib/api";
import { orNull } from "@/lib/errors";
import { PipelineCanvas } from "@/components/pipeline/canvas";

export const dynamic = "force-dynamic";

type Params = Promise<{ id: string; revId: string }>;

/**
 * A pipeline as it stood at one revision — the same canvas, read-only.
 *
 * Reached from a run (which records the `revision_id` it executed) and from
 * the History tab. Both answer the same question: "what did the pipeline
 * actually look like then?" Reusing the canvas rather than a bespoke viewer
 * means the answer is rendered by the same components that render the live
 * spec, so a step can't read one way here and another way there.
 */
export default async function PipelineRevisionPage({
  params,
}: {
  params: Params;
}) {
  const { id, revId } = await params;

  try {
    const revision = await getPipelineRevision(id, revId);
    const pipeline = revision.config;

    // Sources and destinations are not versioned — these are today's rows,
    // resolved from the ids the revision referenced. A since-deleted one
    // renders as "not found", which is the honest answer.
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
        revision={revision}
      />
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}
