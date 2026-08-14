"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { Button, Panel, PanelHead } from "@/components/ui";
import { triggerEval, type EvalSet, type Pipeline } from "@/lib/api";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";
import { eligibleEvalPipelines } from "@/lib/eval-eligibility";

/**
 * Score a config against this corpus.
 *
 * Offers only eval pipelines that read *this set's* documents source. A
 * transform pipeline has nothing to score, and a pipeline reading different
 * documents would match no labels and report zero — a green run that
 * measured nothing. The API refuses both; filtering here means the rejection
 * never has to happen.
 */
export function RunEvalButton({ evalSetId }: { evalSetId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const toast = useToast();
  const { data: pipelines } = useSWR<Pipeline[]>("/api/pipelines");
  const { data: evalSet } = useSWR<EvalSet>(
    `/api/eval-sets/${encodeURIComponent(evalSetId)}`,
  );

  const allEval = (pipelines ?? []).filter(
    (p) => (p as { pipeline_type?: string }).pipeline_type === "eval",
  );
  const evalPipelines = eligibleEvalPipelines(pipelines ?? [], evalSet?.source_id);
  // Distinguishing "none exist" from "none read this corpus" matters: the
  // second is a one-line fix on a pipeline, and saying "no eval pipelines
  // yet" while five exist sends someone off to build a sixth.
  const hiddenByCorpus = allEval.length - evalPipelines.length;

  const run = async (pipelineId: string) => {
    setBusy(pipelineId);
    try {
      const { run_id } = await triggerEval(pipelineId, evalSetId);
      toast.success({
        title: "Eval running",
        message: "Scores land on the leaderboard when it finishes.",
      });
      setOpen(false);
      router.push(`/runs/${run_id}`);
    } catch (e) {
      toast.error(humanizeError(e, { action: "trigger", entity: "eval run" }));
    } finally {
      setBusy(null);
    }
  };

  if (!open) {
    return (
      <Button variant="primary" size="sm" onClick={() => setOpen(true)}>
        Run eval
      </Button>
    );
  }

  return (
    <Panel className="absolute right-0 top-9 z-20 w-[320px] shadow-lg">
      <PanelHead label="Score a config" count={evalPipelines.length} />
      {evalPipelines.length === 0 ? (
        <div className="px-4 py-4 text-[12.5px] text-muted">
          {hiddenByCorpus > 0 ? (
            <>
              {hiddenByCorpus} eval pipeline{hiddenByCorpus === 1 ? "" : "s"} exist
              {hiddenByCorpus === 1 ? "s" : ""}, but none read this set&apos;s
              corpus (
              <code className="font-mono">{evalSet?.source_id}</code>). Labels
              are keyed by document, so scoring a pipeline that reads different
              documents would match nothing and report zero. Point the pipeline
              at this source, or create an eval set for the source it does read.
            </>
          ) : (
            <>
              No eval pipelines yet. Create a pipeline with{" "}
              <code className="font-mono">pipeline_type: eval</code> — documents
              → extract → structure, no destination.
            </>
          )}
        </div>
      ) : (
        evalPipelines.map((p) => (
          <button
            key={p.id}
            type="button"
            disabled={busy !== null}
            onClick={() => void run(p.id)}
            className="w-full text-left px-4 py-2.5 border-b border-border last:border-b-0 hover:bg-hover disabled:opacity-50 bg-transparent cursor-pointer"
          >
            <span className="text-[13px] text-text block">{p.name}</span>
            <span className="font-mono text-[11px] text-subtle">
              {busy === p.id ? "starting…" : p.id}
            </span>
          </button>
        ))
      )}
      <div className="px-4 py-2 border-t border-border">
        <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </Panel>
  );
}
