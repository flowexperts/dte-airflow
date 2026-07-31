"use client";

import { useRouter } from "next/navigation";
import { ParamsModal } from "@/components/params-modal";
import { triggerPipeline, type PipelineParam } from "@/lib/api";

/** Typed trigger dialog. Delegates rendering to `ParamsModal`; owns the
 *  network call + navigate-to-run behaviour. */
export function TriggerModal({
  pipelineId,
  params,
  open,
  onClose,
}: {
  pipelineId: string;
  params: PipelineParam[] | undefined;
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  return (
    <ParamsModal
      title="Trigger run"
      submitLabel="Trigger"
      params={params}
      open={open}
      onClose={onClose}
      emptyMessage={`Run ${pipelineId} now?`}
      onSubmit={async (values) => {
        const { run_id } = await triggerPipeline(pipelineId, values);
        router.push(`/runs/${encodeURIComponent(run_id)}`);
      }}
    />
  );
}
