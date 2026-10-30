import { useState } from "react";
import { Input } from "@/components/ui";

export function LookupMappingsEditor({
  value,
  onChange,
}: {
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}) {
  // Local state so mid-typing rows (empty key or blank value) survive —
  // filtering to `Record<string, string>` on every keystroke would drop
  // rows before the user finishes typing a key, and Add Row would
  // silently vanish.
  const initial = () => Object.entries(value).map(([k, v]) => ({ k, v }));
  const [rows, setRows] = useState<Array<{ k: string; v: string }>>(initial);

  {
    // Sync from parent only when its object shape differs from what our
    // local rows serialise to — otherwise our own commits would echo back
    // and wipe in-flight empty-key rows.
    const serialised: Record<string, string> = {};
    for (const r of rows) if (r.k) serialised[r.k] = r.v;
    const same =
      Object.keys(serialised).length === Object.keys(value).length &&
      Object.entries(serialised).every(([k, v]) => value[k] === v);
    if (!same) setRows(initial());
  }

  const commit = (next: Array<{ k: string; v: string }>) => {
    setRows(next);
    const obj: Record<string, string> = {};
    for (const r of next) if (r.k) obj[r.k] = r.v;
    onChange(obj);
  };
  const updateRow = (i: number, patch: { k?: string; v?: string }) =>
    commit(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const removeRow = (i: number) => commit(rows.filter((_, j) => j !== i));
  const addRow = () => commit([...rows, { k: "", v: "" }]);

  return (
    <div className="border border-border rounded overflow-hidden">
      <div className="grid grid-cols-[1fr_1fr_40px] bg-surface border-b border-border">
        <div className="px-3 py-2 font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle">
          Key
        </div>
        <div className="px-3 py-2 font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle border-l border-border">
          Value
        </div>
        <div className="border-l border-border" />
      </div>
      {rows.length === 0 ? (
        <div className="px-3 py-4 text-center text-subtle text-[12px]">No mappings yet.</div>
      ) : (
        rows.map((r, i) => (
          <div
            key={i}
            className="grid grid-cols-[1fr_1fr_40px] border-b border-border last:border-b-0"
          >
            <div className="px-2 py-1">
              <Input
                value={r.k}
                onChange={(e) => updateRow(i, { k: e.target.value })}
                placeholder="US"
              />
            </div>
            <div className="px-2 py-1 border-l border-border">
              <Input
                value={r.v}
                onChange={(e) => updateRow(i, { v: e.target.value })}
                placeholder="United States"
              />
            </div>
            <div className="border-l border-border flex items-center justify-center">
              <button
                type="button"
                onClick={() => removeRow(i)}
                className="w-full h-full text-subtle hover:text-red text-lg leading-none"
                aria-label={`Remove row ${i + 1}`}
                title="Delete row"
              >
                ×
              </button>
            </div>
          </div>
        ))
      )}
      <div className="bg-surface border-t border-border">
        <button
          type="button"
          onClick={addRow}
          className="w-full px-3 py-2 font-mono text-[10.5px] tracking-[0.18em] uppercase text-accent hover:text-accent-h hover:bg-code-bg text-left"
        >
          + Add row
        </button>
      </div>
    </div>
  );
}
