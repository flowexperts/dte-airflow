"use client";

import { useState } from "react";
import useSWR from "swr";
import { Button, Dropdown, Input, Panel, PanelHead } from "@/components/ui";
import { listEvalSets, upsertEvalExample, type EvalSet } from "@/lib/api";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";
import { usePermissions } from "@/lib/use-permissions";

/**
 * Labeling as a byproduct of reviewing.
 *
 * This is the highest-leverage of plan 051's four labeling paths, and the
 * reason is entirely about where it sits rather than what it does. Someone
 * looking at the inspector is *already* checking an extracted value against
 * the rendered page — the exact judgement a label encodes. Asking them to
 * go elsewhere and retype it is how eval sets end up empty.
 *
 * **Correct** writes what the extractor produced, unchanged, in one click:
 * the common case, and it must not cost more than a glance. **Fix** opens
 * the values for editing, because the moment worth capturing most is the
 * one where the extractor was wrong — that document is worth more to the
 * corpus than ten it got right.
 *
 * Written as `human` regardless of which button was used. A person confirmed
 * it against the page; that is what `human` means here, and quietly tagging
 * an accepted value as `consensus` or `judge` would corrupt the one signal
 * the leaderboard's provenance warning depends on.
 */
export function LabelFromInspector({
  docKey,
  docRef,
  values,
}: {
  docKey: string;
  docRef?: string | null;
  /** The extracted values, pre-filled as the proposed label. */
  values: Record<string, unknown>;
}) {
  const { can } = usePermissions();
  const [setId, setSetId] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const { data: sets } = useSWR<EvalSet[]>(
    can("eval:write") ? ["eval-sets", "inspector"] : null,
    () => listEvalSets(),
  );

  if (!can("eval:write")) return null;

  const available = sets ?? [];
  // With exactly one set there is nothing to choose, so don't make them.
  const activeId = setId || (available.length === 1 ? available[0]!.id : "");
  const active = available.find((s) => s.id === activeId);
  const fieldNames = active ? active.field_specs.map((f) => f.name) : [];

  const openFix = () => {
    const seed: Record<string, string> = {};
    for (const f of fieldNames) seed[f] = values[f] == null ? "" : String(values[f]);
    setDraft(seed);
    setEditing(true);
  };

  const save = async (labels: Record<string, unknown>) => {
    if (!activeId) return;
    setBusy(true);
    try {
      const res = await upsertEvalExample(activeId, {
        doc_key: docKey,
        doc_ref: docRef ?? null,
        labels,
        label_source: "human",
      });
      toast.success({
        title: "Saved as ground truth",
        message: `${active?.name ?? activeId} is now at labels v${res.labels_version}.`,
      });
      setEditing(false);
    } catch (e) {
      toast.error(humanizeError(e, { action: "save", entity: "label" }));
    } finally {
      setBusy(false);
    }
  };

  const saveAsIs = () => {
    const labels: Record<string, unknown> = {};
    // Only fields the set actually scores, and only ones with a value. An
    // empty string written as ground truth asserts "the right answer is
    // nothing", which makes every abstaining extractor look correct.
    for (const f of fieldNames) {
      if (values[f] != null && values[f] !== "") labels[f] = values[f];
    }
    void save(labels);
  };

  const saveFixed = () => {
    const labels: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(draft)) {
      if (v.trim() !== "") labels[k] = v.trim();
    }
    void save(labels);
  };

  return (
    <Panel>
      <PanelHead label="Use as ground truth" />
      <div className="px-4 py-3 flex flex-col gap-3">
        {available.length === 0 ? (
          <p className="text-[12.5px] text-subtle">
            No eval sets yet. Create one to start collecting labels while you
            review.
          </p>
        ) : (
          <>
            {available.length > 1 && (
              <Dropdown
                value={activeId}
                onChange={setSetId}
                placeholder="— which eval set? —"
                options={available.map((s) => ({ value: s.id, label: s.name }))}
              />
            )}

            {editing ? (
              <div className="flex flex-col gap-2">
                {fieldNames.map((f) => (
                  <label key={f} className="flex flex-col gap-1">
                    <span className="text-[11px] text-subtle uppercase tracking-wide">
                      {f}
                    </span>
                    <Input
                      value={draft[f] ?? ""}
                      onChange={(e) =>
                        setDraft((d) => ({ ...d, [f]: e.target.value }))
                      }
                      placeholder="leave blank if the document doesn't say"
                    />
                  </label>
                ))}
                <div className="flex items-center gap-2">
                  <Button variant="primary" size="sm" disabled={busy} onClick={saveFixed}>
                    {busy ? "Saving…" : "Save corrected"}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
                    Cancel
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  disabled={busy || !activeId}
                  onClick={saveAsIs}
                >
                  {busy ? "Saving…" : "Correct"}
                </Button>
                <Button variant="default" size="sm" disabled={!activeId} onClick={openFix}>
                  Fix…
                </Button>
                <span className="text-[11.5px] text-subtle">
                  Saved as a human label against the document&apos;s hash, so it
                  survives renames.
                </span>
              </div>
            )}
          </>
        )}
      </div>
    </Panel>
  );
}
