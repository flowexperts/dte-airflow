import { useState } from "react";
import { Button, Input, Panel, PanelHead } from "@/components/ui";
import { DestinationPicker } from "@/components/builder/DestinationPicker";
import { promoteEvalPipeline } from "@/lib/api";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";
import { usePermissions } from "@/lib/use-permissions";

/**
 * Ship the config that won.
 *
 * This closes the loop the harness exists for. Everything upstream answers
 * "which extraction config should I ship"; without this, the answer is a
 * number on a leaderboard that someone re-types into the builder by hand —
 * which is exactly where the config that was *measured* and the config that
 * actually *ships* start to diverge, silently and permanently.
 *
 * The backend copies the steps verbatim so the promoted pipeline hashes to
 * the same `config_digest` that earned the score. The digest is echoed back
 * here rather than hidden, because "same digest" is the only real evidence
 * that what shipped is what was measured.
 */
/**
 * The promote form itself, without the control that opens it.
 *
 * Shared by the leaderboard (where a ranked row is promoted) and the
 * comparison (where the user picks the config first, because no rank
 * exists). Both must produce the same request and the same digest echo —
 * two implementations would drift, and the drift would be invisible until
 * a promoted pipeline stopped matching what was measured.
 *
 * `pipelineId` may be empty: the comparison's chooser renders this before a
 * config is picked, and the submit stays disabled until it is.
 */
export function PromoteForm({
  evalSetId,
  pipelineId,
  onDone,
  onCancel,
}: {
  evalSetId: string;
  pipelineId: string;
  onDone?: () => void;
  onCancel?: () => void;
}) {
  const [newId, setNewId] = useState("");
  const [name, setName] = useState("");
  const [outputId, setOutputId] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const go = async () => {
    setBusy(true);
    try {
      const res = await promoteEvalPipeline(evalSetId, {
        pipeline_id: pipelineId,
        new_pipeline_id: newId.trim(),
        name: name.trim() || newId.trim(),
        output_id: outputId,
      });
      toast.success({
        title: `Promoted to ${res.pipeline_id}`,
        message: `Same config digest (${res.config_digest.slice(0, 12)}) — what ships is what was scored.`,
      });
      onDone?.();
    } catch (e) {
      toast.error(humanizeError(e, { action: "promote", entity: "pipeline" }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
          <p className="text-[12.5px] text-muted">
            Copies this exact extract + structure config into a transform
            pipeline. The steps are copied verbatim, so the promoted pipeline
            keeps the digest that earned the score.
          </p>
          <div className="grid grid-cols-2 gap-2">
            <Input
              value={newId}
              onChange={(e) => setNewId(e.target.value)}
              placeholder="new pipeline id"
            />
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="display name"
            />
          </div>
          {/* The builder's own picker, not a plain dropdown of what already
              exists. Promote *creates a pipeline*, so the destination it
              writes to very often does not exist yet — and a list with no way
              to add to it reads as "you must have prepared one first", which
              is not true. `DestinationPicker` carries "+ Create new
              destination…" and Edit inline, and it is the same control the
              builder uses for the same slot, so the two surfaces cannot
              drift on what a valid destination looks like. */}
          <DestinationPicker outputId={outputId} onChange={setOutputId} />
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              disabled={busy || !pipelineId || !newId.trim() || !outputId}
              onClick={() => void go()}
            >
              {busy ? "Promoting…" : "Promote"}
            </Button>
            {onCancel && (
              <Button variant="ghost" size="sm" onClick={onCancel}>
                Cancel
              </Button>
            )}
          </div>
    </>
  );
}

/**
 * The leaderboard's entry point: a ranked row is already the chosen config,
 * so the control opens straight onto the form.
 */
export function PromoteButton({
  evalSetId,
  pipelineId,
}: {
  evalSetId: string;
  pipelineId: string;
}) {
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);

  if (!can("eval:write")) return null;

  if (!open) {
    return (
      <button
        type="button"
        className="text-[11.5px] text-subtle hover:text-[color:var(--accent)]"
        onClick={() => setOpen(true)}
        title="Copy this config into a transform pipeline that writes real output"
      >
        Promote
      </button>
    );
  }

  return (
    <div className="w-full mt-2">
      <Panel>
        <PanelHead label={`Promote ${pipelineId}`} />
        <div className="px-4 py-3 flex flex-col gap-2">
          <PromoteForm
            evalSetId={evalSetId}
            pipelineId={pipelineId}
            onDone={() => setOpen(false)}
            onCancel={() => setOpen(false)}
          />
        </div>
      </Panel>
    </div>
  );
}
