"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui";
import { usePermissions } from "@/lib/use-permissions";
import { isSweepVariant, rootPipelineId } from "@/lib/pipeline-variant";
import { evalSetForPipeline, pipelineAsEval, type Pipeline } from "@/lib/api";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";

/**
 * Turn an extraction pipeline into one that can be compared.
 *
 * This used to open a wizard that configured a matrix and launched it in one
 * transient step. The matrix now lives on the eval pipeline (plan 055), so
 * the button's job is only the part that had to happen first: derive the
 * eval twin and its set, then hand the user to the pipeline where the
 * comparison is configured and run.
 *
 * Both derivations are idempotent — Compare is a button people press twice,
 * and a second press must not accumulate `__eval__eval`, each with its own
 * runs diluting one leaderboard.
 */
export function CompareButton({ pipeline }: { pipeline: Pipeline }) {
  const { can } = usePermissions();
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  // Nothing to compare configs *of*. Hiding the button beats offering it
  // and rejecting the click with a message about structure steps.
  const hasStructure = (pipeline.steps ?? []).some(
    (s) => (s as { op?: string }).op === "structure",
  );
  if (!hasStructure || !can("eval:write")) return null;

  /*
   * A sweep cell is an artifact of a comparison, not a config anyone wrote.
   * Comparing one used to nest it under itself —
   * `demo_eval_strict__27fb9c1d2679__27fb9c1d2679__37f7b8bbec71` — and each
   * round silently varied a setting the previous round had already pinned,
   * so people compared against a config they never chose.
   *
   * Link to the root rather than sweeping from here. Hiding the control
   * entirely would leave someone on a variant with no way back to the
   * comparison they actually want.
   */
  if (isSweepVariant(pipeline.id)) {
    return (
      <Button
        variant="default"
        size="sm"
        href={`/pipelines/${encodeURIComponent(rootPipelineId(pipeline.id))}`}
        title="This is one cell of a comparison. Compare from the config it came from."
      >
        Compare from the original
      </Button>
    );
  }

  /* An eval pipeline already *is* the thing that carries a matrix — the
     panel is on this page. Sending someone away to configure what is in
     front of them would be a detour through their own pipeline. */
  if (pipeline.pipeline_type === "eval") return null;

  const go = async () => {
    setBusy(true);
    try {
      const { pipeline_id } = await pipelineAsEval(pipeline.id);
      await evalSetForPipeline(pipeline_id);
      toast.success({
        title: "Eval twin ready",
        message: "Configure the comparison here, then run it.",
      });
      router.push(`/pipelines/${encodeURIComponent(pipeline_id)}`);
    } catch (e) {
      toast.error(humanizeError(e, { action: "prepare", entity: "comparison" }));
      setBusy(false);
    }
  };

  return (
    <Button
      variant="default"
      size="sm"
      disabled={busy}
      onClick={() => void go()}
      title="Create an eval copy of this pipeline and configure a comparison on it"
    >
      {busy ? "Preparing…" : "Compare…"}
    </Button>
  );
}
