"use client";

import { useState } from "react";
import useSWR from "swr";
import { Button, Panel, PanelHead } from "@/components/ui";
import {
  createDestination,
  updateDestination,
  isJsonFileOutput,
  type Destination,
} from "@/lib/api";
import { OutputPanel } from "./OutputPanel";

function emptyDestination(id: string): Destination {
  return {
    id,
    config: { type: "json_file", path: "./out/result.json", fields: [] },
  };
}

export function DestinationPicker({
  outputId,
  onChange,
}: {
  outputId: string;
  onChange: (next: string) => void;
}) {
  const { data: available = [], mutate } = useSWR<Destination[]>("/api/destinations");
  const [editing, setEditing] = useState<{ draft: Destination; isNew: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const openNew = () => {
    const suggested = `destination_${available.length + 1}`;
    setEditing({ draft: emptyDestination(suggested), isNew: true });
    setErr(null);
  };
  const openEdit = () => {
    const existing = available.find((d) => d.id === outputId);
    if (!existing) {
      setErr(`Destination '${outputId}' not found on server.`);
      return;
    }
    setEditing({ draft: existing, isNew: false });
    setErr(null);
  };

  const saveDraft = async () => {
    if (!editing) return;
    setBusy(true);
    setErr(null);
    try {
      if (editing.isNew) {
        await createDestination(editing.draft);
        onChange(editing.draft.id);
      } else {
        await updateDestination(editing.draft.id, editing.draft);
      }
      await mutate();
      setEditing(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const chosen = available.find((d) => d.id === outputId);

  return (
    <Panel>
      <PanelHead label="Destination" />
      <div className="flex items-center gap-2 p-3 border-b border-border">
        <select
          className="flex-1 bg-transparent border border-border rounded px-2 py-1 font-mono text-[12px]"
          value={outputId}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="" disabled>
            — pick a destination —
          </option>
          {available.map((d) => (
            <option key={d.id} value={d.id}>
              {d.id} · {d.config.type}
              {"path" in d.config && d.config.path ? ` · ${d.config.path}` : ""}
            </option>
          ))}
          {outputId && !chosen && <option value={outputId}>{outputId} (missing)</option>}
        </select>
        {outputId && chosen && (
          <button
            type="button"
            onClick={openEdit}
            className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
            title="shared with other pipelines"
          >
            Edit
          </button>
        )}
      </div>

      {editing && (
        <div className="border-t-2 border-accent bg-code-bg p-4 space-y-3">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-accent">
              {editing.isNew ? "New destination" : `Editing ${editing.draft.id}`}
              {!editing.isNew && (
                <span className="ml-2 text-subtle normal-case tracking-normal">
                  · shared with other pipelines
                </span>
              )}
            </span>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setEditing(null)}
                disabled={busy}
              >
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={saveDraft}
                disabled={busy}
              >
                {busy ? "Saving…" : "Save destination"}
              </Button>
            </div>
          </div>
          {err && (
            <div className="font-mono text-[11.5px] text-red">{err}</div>
          )}
          {editing.isNew && (
            <input
              className="w-full bg-transparent border border-border rounded px-2 py-1 font-mono text-[12px]"
              value={editing.draft.id}
              onChange={(e) =>
                setEditing({ ...editing, draft: { ...editing.draft, id: e.target.value } })
              }
              placeholder="destination_id"
            />
          )}
          {isJsonFileOutput(editing.draft.config) ? (
            <OutputPanel
              output={editing.draft.config}
              onChange={(cfg) =>
                setEditing({ ...editing, draft: { ...editing.draft, config: cfg } })
              }
            />
          ) : (
            <div className="border border-border rounded p-4 text-sm text-subtle bg-surface">
              {editing.draft.config.type} destinations aren&apos;t editable in
              the UI yet.
            </div>
          )}
        </div>
      )}

      {!editing && (
        <button
          type="button"
          onClick={openNew}
          className="w-full text-center py-3 px-3.5 border-t border-dashed border-border font-medium text-xs text-subtle hover:text-accent hover:bg-[color:var(--accent-tint)] transition-colors"
        >
          <span className="text-accent font-bold mr-1">+</span> New destination
        </button>
      )}
    </Panel>
  );
}
