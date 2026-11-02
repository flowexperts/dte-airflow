import { useState } from "react";
import { useRouter } from "@/lib/nav";
import { ParamsModal } from "@/components/params-modal";
import { Button } from "@/components/ui";
import useSWR from "swr";
import { estimatePipeline, triggerPipeline, type Pipeline, type PipelineEstimate } from "@/lib/api";
import { useReadsMetered } from "@/lib/metered";
import { usePermissions } from "@/lib/use-permissions";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";

/**
 * Trigger that always goes through the params modal — the list's old inline
 * `▶ Run` called `triggerPipeline(id)` with no params, which fails outright on
 * any pipeline that declares a required input.
 *
 * `onStarted` lets a caller keep the user in place and show the run inline.
 * Without it we fall back to navigating, matching the existing behaviour.
 */
export function TriggerRunButton({
  pipeline,
  variant = "micro",
  onStarted,
}: {
  pipeline: Pipeline;
  variant?: "micro" | "primary";
  onStarted?: (runId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const toast = useToast();
  const { can } = usePermissions();
  // Plan 093: judge a warehouse run when the modal opens. A small run says
  // nothing and starts on the one Run click; a big one says what it costs in
  // words people use; one over the connection's cap can't be started. A
  // trigger that still answers with an estimate (inputs changed what it
  // reads, or Run beat the estimate) lands in `answered` and asks once more.
  const metered = useReadsMetered(pipeline.sources) === true;
  const { data: opened } = useSWR(open && metered ? ["estimate", pipeline.id] : null, () =>
    estimatePipeline(pipeline).catch(() => null),
  );
  const [answered, setAnswered] = useState<PipelineEstimate | null>(null);
  const estimate = answered ?? opened ?? null;

  if (!can("pipeline:trigger")) return null;

  const stop = (e: React.MouseEvent) => {
    e.stopPropagation();
    setOpen(true);
  };

  return (
    <>
      {variant === "primary" ? (
        <Button variant="primary" size="sm" onClick={stop}>
          ▶ Run
        </Button>
      ) : (
        <button
          type="button"
          onClick={stop}
          className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
        >
          ▶ Run
        </button>
      )}
      <ParamsModal
        title={`Run ${pipeline.name}`}
        submitLabel="Run"
        params={pipeline.params}
        open={open}
        onClose={() => {
          setOpen(false);
          setAnswered(null);
        }}
        emptyMessage={`Run ${pipeline.name} now?`}
        notice={estimate?.needs_confirm ? estimate.message : null}
        submitDisabled={!!estimate?.exceeds_cap}
        onSubmit={async (values) => {
          try {
            const res = await triggerPipeline(pipeline.id, values, !!estimate?.needs_confirm);
            if ("estimate" in res) {
              setAnswered(res.estimate);
              return;
            }
            if (!("run_id" in res)) return;
            const { run_id } = res;
            // Close on success. Navigating used to hide the omission by
            // unmounting the modal, but that only happens on the `router.push`
            // branch — with an `onStarted` handler nothing navigates and the
            // modal sat open over a run that had already started.
            setOpen(false);
            setAnswered(null);
            if (onStarted) {
              onStarted(run_id);
            } else {
              router.push(`/runs/detail?id=${encodeURIComponent(run_id)}`);
            }
          } catch (e) {
            // Deliberately left open on failure: the toast says what went
            // wrong and the user keeps the values they typed to retry.
            toast.error(humanizeError(e, { action: "start", entity: "pipeline" }));
          }
        }}
      />
    </>
  );
}
