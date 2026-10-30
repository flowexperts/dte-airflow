import { useState } from "react";
import useSWR from "swr";
import { Button, Dropdown, Panel, PanelHead, type DropdownOption } from "@/components/ui";
import { createDestination, updateDestination, isFileOutput, type Destination } from "@/lib/api";
import { OutputPanel } from "./OutputPanel";

function emptyDestination(name: string): Destination {
  return {
    id: "",
    name,
    connection_id: "local_fs",
    config: { type: "json", path: "./out/result.json", fields: [] },
  };
}

export function DestinationPicker({
  outputId,
  onChange,
  error,
}: {
  outputId: string;
  onChange: (next: string) => void;
  /** Validation error to display beneath the panel. */
  error?: string | undefined;
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
        // Server generates the id — use the response, not the draft.
        const created = await createDestination(editing.draft);
        onChange(created.id);
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
        <div className="flex-1">
          <Dropdown<string>
            value={outputId}
            onChange={onChange}
            placeholder="— pick a destination —"
            options={[
              { kind: "action", label: "+ Create new destination…", onSelect: openNew },
              ...(available.length > 0 ? ([{ kind: "divider" }] as DropdownOption<string>[]) : []),
              ...available.map<DropdownOption<string>>((d) => ({
                value: d.id,
                label: d.name ?? d.id,
                meta: "path" in d.config && d.config.path ? d.config.path : d.config.type,
              })),
              ...(outputId && !chosen
                ? ([
                    { value: outputId, label: `${outputId} (missing)`, disabled: true },
                  ] as DropdownOption<string>[])
                : []),
            ]}
          />
        </div>
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
              {editing.isNew
                ? "New destination"
                : `Editing ${editing.draft.name ?? editing.draft.id}`}
              {!editing.isNew && (
                <span className="ml-2 text-subtle normal-case tracking-normal">
                  · shared with other pipelines
                </span>
              )}
            </span>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={() => setEditing(null)} disabled={busy}>
                Cancel
              </Button>
              <Button variant="primary" size="sm" onClick={saveDraft} disabled={busy}>
                {busy ? "Saving…" : "Save destination"}
              </Button>
            </div>
          </div>
          {err && <div className="font-mono text-[11.5px] text-red">{err}</div>}
          <input
            className="w-full bg-transparent border border-border rounded px-2 py-1 text-[13px]"
            value={editing.draft.name ?? ""}
            onChange={(e) =>
              setEditing({ ...editing, draft: { ...editing.draft, name: e.target.value } })
            }
            placeholder="Name (editable, unique)"
          />
          {!editing.isNew && (
            <div className="text-xs text-subtle font-mono">id: {editing.draft.id}</div>
          )}
          {isFileOutput(editing.draft.config) ? (
            <OutputPanel
              output={editing.draft.config}
              onChange={(cfg) =>
                setEditing({ ...editing, draft: { ...editing.draft, config: cfg } })
              }
            />
          ) : (
            <div className="border border-border rounded p-4 text-sm text-subtle bg-surface">
              {editing.draft.config.type} destinations aren&apos;t editable in the UI yet.
            </div>
          )}
        </div>
      )}

      {error && <div className="px-3 pb-2 font-mono text-[11.5px] text-red">{error}</div>}
    </Panel>
  );
}
