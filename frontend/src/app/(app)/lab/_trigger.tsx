"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ParamsModal } from "@/components/params-modal";
import { Button } from "@/components/ui";
import { triggerPipeline, type Pipeline } from "@/lib/api";
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
export function LabTriggerButton({
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
        onClose={() => setOpen(false)}
        emptyMessage={`Run ${pipeline.name} now?`}
        onSubmit={async (values) => {
          try {
            const { run_id } = await triggerPipeline(pipeline.id, values);
            if (onStarted) {
              onStarted(run_id);
            } else {
              router.push(`/lab/runs/${encodeURIComponent(run_id)}`);
            }
          } catch (e) {
            toast.error(humanizeError(e, { action: "start", entity: "pipeline" }));
          }
        }}
      />
    </>
  );
}
