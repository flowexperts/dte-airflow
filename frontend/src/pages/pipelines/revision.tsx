import { useSearchParams } from "@/lib/nav";
import useSWR from "swr";
import {
  getDestination,
  getPipelineRevision,
  getSource,
  type Destination,
  type Source,
} from "@/lib/api";
import { orNull } from "@/lib/errors";
import { InlineError } from "@/components/ui";
import { MissingParam } from "@/components/missing-param";
import { withSuspense } from "@/components/with-suspense";
import { PipelineCanvas } from "@/components/pipeline/canvas";

/**
 * A pipeline as it stood at one revision — the same canvas, read-only.
 * Reached from a run (which records the `revision_id` it executed) and from
 * the History tab. Reusing the canvas means a step can't read one way here
 * and another way in the live spec.
 */
function PipelineRevisionPage() {
  const q = useSearchParams();
  const id = q.get("id");
  const revId = q.get("rev");
  const { data, error } = useSWR(
    id && revId ? ["pipeline-rev", id, revId] : null,
    async () => {
      const revision = await getPipelineRevision(id!, revId!);
      const pipeline = revision.config;
      // Sources and destinations are not versioned — these are today's rows.
      const [sources, destination] = await Promise.all([
        Promise.all(
          (pipeline.sources ?? []).map((ref) => getSource(ref.source_id).catch(orNull<Source>)),
        ),
        pipeline.output_id
          ? getDestination(pipeline.output_id).catch(orNull<Destination>)
          : Promise.resolve(null),
      ]);
      return { revision, pipeline, sources, destination };
    },
    { revalidateOnFocus: false },
  );

  if (!id || !revId) return <MissingParam what="revision" />;
  if (error) {
    return (
      <div className="px-14 py-8">
        <InlineError title="Couldn't load this revision" message="It may not exist." />
      </div>
    );
  }
  if (!data) return <div className="px-14 py-8 text-subtle font-mono text-sm">Loading…</div>;
  return (
    <PipelineCanvas
      key={`${id}:${revId}`}
      initialPipeline={data.pipeline}
      sources={data.sources}
      destination={data.destination}
      revision={data.revision}
    />
  );
}

export default withSuspense(PipelineRevisionPage);
