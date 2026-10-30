import { useState } from "react";
import useSWR from "swr";
import {
  Button,
  Dropdown,
  Panel,
  PanelHead,
  Field,
  Input,
  type DropdownOption,
} from "@/components/ui";
import { createLookupTable, updateLookupTable, type LookupTable } from "@/lib/api";
import { LookupMappingsEditor } from "@/components/lookup-mappings-editor";

function emptyLookup(id: string): LookupTable {
  return { id, name: null, mappings: {}, default: null };
}

export function LookupTablePicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (next: string) => void;
}) {
  const { data: available = [], mutate } = useSWR<LookupTable[]>("/api/lookup-tables");
  const [editing, setEditing] = useState<{ draft: LookupTable; isNew: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const openNew = () => {
    const suggested = `lookup_${available.length + 1}`;
    setEditing({ draft: emptyLookup(suggested), isNew: true });
    setErr(null);
  };
  const openEdit = () => {
    const existing = available.find((l) => l.id === value);
    if (!existing) {
      setErr(`Lookup table '${value}' not found on server.`);
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
        await createLookupTable(editing.draft);
        onChange(editing.draft.id);
      } else {
        await updateLookupTable(editing.draft.id, editing.draft);
      }
      await mutate();
      setEditing(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const chosen = available.find((l) => l.id === value);

  return (
    <Panel>
      <PanelHead label="Lookup table" />
      <div className="flex items-center gap-2 p-3 border-b border-border">
        <div className="flex-1">
          <Dropdown<string>
            value={value}
            onChange={onChange}
            placeholder="— pick a lookup table —"
            options={[
              { kind: "action", label: "+ Create new lookup table…", onSelect: openNew },
              ...(available.length > 0 ? ([{ kind: "divider" }] as DropdownOption<string>[]) : []),
              ...available.map<DropdownOption<string>>((l) => ({
                value: l.id,
                label: l.id,
                meta: `${Object.keys(l.mappings || {}).length} entries`,
              })),
              ...(value && !chosen
                ? ([
                    { value, label: `${value} (missing)`, disabled: true },
                  ] as DropdownOption<string>[])
                : []),
            ]}
          />
        </div>
        {value && chosen && (
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
              {editing.isNew ? "New lookup table" : `Editing ${editing.draft.id}`}
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
                {busy ? "Saving…" : "Save lookup"}
              </Button>
            </div>
          </div>
          {err && <div className="font-mono text-[11.5px] text-red">{err}</div>}
          {editing.isNew && (
            <input
              className="w-full bg-transparent border border-border rounded px-2 py-1 font-mono text-[12px]"
              value={editing.draft.id}
              onChange={(e) =>
                setEditing({ ...editing, draft: { ...editing.draft, id: e.target.value } })
              }
              placeholder="lookup_id"
            />
          )}
          <Field label="Name (optional)">
            <Input
              value={editing.draft.name ?? ""}
              onChange={(e) =>
                setEditing({
                  ...editing,
                  draft: { ...editing.draft, name: e.target.value || null },
                })
              }
              placeholder="Country names"
            />
          </Field>
          <Field label="Default" hint="value used when no match">
            <Input
              value={editing.draft.default ?? ""}
              onChange={(e) =>
                setEditing({
                  ...editing,
                  draft: { ...editing.draft, default: e.target.value || null },
                })
              }
              placeholder="OTHER"
            />
          </Field>
          <Field label="Mappings" hint="key on the left, replacement value on the right">
            <LookupMappingsEditor
              value={editing.draft.mappings}
              onChange={(m) => setEditing({ ...editing, draft: { ...editing.draft, mappings: m } })}
            />
          </Field>
        </div>
      )}
    </Panel>
  );
}
