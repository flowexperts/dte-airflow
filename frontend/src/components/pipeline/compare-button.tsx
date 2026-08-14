"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui";
import { CompareWizard } from "@/components/evals/compare-wizard";
import { usePermissions } from "@/lib/use-permissions";
import { isSweepVariant, rootPipelineId } from "@/lib/pipeline-variant";
import type { Pipeline } from "@/lib/api";

/**
 * The entry point to comparing extraction configs.
 *
 * It sits on the pipeline, not on an eval set, because that is where the
 * user already is. Plan 051 put the entry on `/eval-sets` — an abstract
 * object you had to define from scratch, naming a source and retyping a
 * field list the pipeline already declared. Everything the eval set needs
 * is sitting in the pipeline; asking for it again is what made the flow
 * 28 steps long.
 *
 * Shown for transform and eval pipelines alike: an eval pipeline is its
 * own twin, so the flow is identical from here on.
 */
export function CompareButton({ pipeline }: { pipeline: Pipeline }) {
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);

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
      <Link
        href={`/pipelines/${encodeURIComponent(rootPipelineId(pipeline.id))}`}
        className="text-[12.5px] text-muted hover:text-text underline underline-offset-2"
        title="This is one cell of a comparison. Compare from the config it came from."
      >
        Compare from the original
      </Link>
    );
  }

  return (
    <div className="relative">
      <Button variant="default" size="sm" onClick={() => setOpen((v) => !v)}>
        Compare…
      </Button>
      {open && <CompareWizard pipeline={pipeline} onClose={() => setOpen(false)} />}
    </div>
  );
}
