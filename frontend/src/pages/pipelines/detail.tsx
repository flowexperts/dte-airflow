import { useSearchParams } from "@/lib/nav";
import useSWR from "swr";
import { getDestination, getPipeline, getSource, type Destination, type Source } from "@/lib/api";
import { orNull } from "@/lib/errors";
import { InlineError } from "@/components/ui";
import { MissingParam } from "@/components/missing-param";
import { withSuspense } from "@/components/with-suspense";
import { PipelineCanvas } from "@/components/pipeline/canvas";

function PipelineDetail() {
  const id = useSearchParams().get("id");
  const { data, error } = useSWR(id ? ["pipeline-view", id] : null, async () => {
    const pipeline = await getPipeline(id!);
    // A missing source or destination is a state the page must render, not an
    // error — the canvas shows it as "not found" so it can be fixed in place.
    const [sources, destination] = await Promise.all([
      Promise.all(
        (pipeline.sources ?? []).map((ref) => getSource(ref.source_id).catch(orNull<Source>)),
      ),
      pipeline.output_id
        ? getDestination(pipeline.output_id).catch(orNull<Destination>)
        : Promise.resolve(null),
    ]);
    return { pipeline, sources, destination };
  }, { revalidateOnFocus: false });

  if (!id) return <MissingParam what="pipeline" />;
  if (error) {
    return (
      <div className="px-14 py-8">
        <InlineError title="Couldn't load this pipeline" message="It may have been deleted." />
      </div>
    );
  }
  if (!data) return <div className="px-14 py-8 text-subtle font-mono text-sm">Loading…</div>;
  return (
    <PipelineCanvas
      key={id}
      initialPipeline={data.pipeline}
      sources={data.sources}
      destination={data.destination}
    />
  );
}

export default withSuspense(PipelineDetail);
