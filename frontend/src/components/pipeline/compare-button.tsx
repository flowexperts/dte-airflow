import { useState } from "react";
import { useRouter } from "@/lib/nav";
import { Button } from "@/components/ui";
import { usePermissions } from "@/lib/use-permissions";
import { isSweepVariant, rootPipelineId } from "@/lib/pipeline-variant";
import { evalSetForPipeline, pipelineAsEval, type Pipeline } from "@/lib/api";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";
import { CompareDialog } from "@/components/evals/compare-dialog";

/**
 * Turn an extraction pipeline into one that can be compared — and, for a
 * pipeline that already is an eval pipeline, open the comparison launcher.
 *
 * The matrix lives on the eval pipeline (plan 055), but editing it is on
 * demand from here rather than a block sitting permanently open above the
 * steps — most visits to an eval pipeline are to look at what it does or
 * how it last scored, not to launch a new comparison.
 *
 * Both eval-twin derivations are idempotent — Compare is a button people
 * press twice, and a second press must not accumulate `__eval__eval`, each
 * with its own runs diluting one leaderboard.
 */
export function CompareButton({
  pipeline,
  onMatrixChange,
}: {
  pipeline: Pipeline;
  /** Only used when `pipeline.pipeline_type === "eval"` — persists matrix
   *  edits the same way the rest of the pipeline is edited (dirty + Save). */
  onMatrixChange?: (matrix: Record<string, string[]> | null) => void;
}) {
  const { can } = usePermissions();
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

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
        href={`/pipelines/detail?id=${encodeURIComponent(rootPipelineId(pipeline.id))}`}
        title="This is one cell of a comparison. Compare from the config it came from."
      >
        Compare from the original
      </Button>
    );
  }

  /* An eval pipeline already *is* the thing that carries a matrix — this
     button opens the launcher on it rather than sending someone away. */
  if (pipeline.pipeline_type === "eval") {
    return (
      <>
        <Button
          variant="default"
          size="sm"
          onClick={() => setDialogOpen(true)}
          title="Configure and run a comparison over this pipeline's providers, models or prompts"
        >
          Compare…
        </Button>
        <CompareDialog
          pipeline={pipeline}
          onChange={onMatrixChange ?? (() => {})}
          readOnly={!can("eval:write")}
          open={dialogOpen}
          onClose={() => setDialogOpen(false)}
        />
      </>
    );
  }

  const go = async () => {
    setBusy(true);
    try {
      const { pipeline_id } = await pipelineAsEval(pipeline.id);
      await evalSetForPipeline(pipeline_id);
      toast.success({
        title: "Eval twin ready",
        message: "Press Compare… here to configure and run it.",
      });
      router.push(`/pipelines/detail?id=${encodeURIComponent(pipeline_id)}`);
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
