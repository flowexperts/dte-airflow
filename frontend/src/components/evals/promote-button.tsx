"use client";

import { useState } from "react";
import useSWR from "swr";
import { Button, Dropdown, Input, Panel, PanelHead } from "@/components/ui";
import {
  listDestinations,
  promoteEvalPipeline,
  type Destination,
} from "@/lib/api";
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
export function PromoteButton({
  evalSetId,
  pipelineId,
}: {
  evalSetId: string;
  pipelineId: string;
}) {
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);
  const [newId, setNewId] = useState("");
  const [name, setName] = useState("");
  const [outputId, setOutputId] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const { data: destinations } = useSWR<Destination[]>(
    open ? ["destinations", "promote"] : null,
    () => listDestinations(),
  );

  if (!can("eval:write")) return null;

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
      setOpen(false);
    } catch (e) {
      toast.error(humanizeError(e, { action: "promote", entity: "pipeline" }));
    } finally {
      setBusy(false);
    }
  };

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
          <Dropdown
            value={outputId}
            onChange={setOutputId}
            placeholder="— where should it write? —"
            options={(destinations ?? []).map((d) => ({
              value: d.id,
              label: d.name ?? d.id,
            }))}
          />
          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              disabled={busy || !newId.trim() || !outputId}
              onClick={() => void go()}
            >
              {busy ? "Promoting…" : "Promote"}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
              Cancel
            </Button>
          </div>
        </div>
      </Panel>
    </div>
  );
}
