"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  Button,
  DataTable,
  Field,
  Input,
  PageHeader,
  Panel,
  Topbar,
  type Column,
  type DataTableSelection,
} from "@/components/ui";
import {
  bulkDeleteLookupTables,
  createLookupTable,
  deleteLookupTable,
  updateLookupTable,
  type BulkDeleteResult,
  type LookupTable,
} from "@/lib/api";
import { summarizeBulkDelete } from "@/lib/bulk-delete";
import { LookupMappingsEditor } from "@/components/lookup-mappings-editor";
import { usePermissions } from "@/lib/use-permissions";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";

function emptyLookup(id: string): LookupTable {
  return { id, name: null, mappings: {}, default: null };
}

function LookupEditorPanel({
  draft,
  isNew,
  busy,
  err,
  onChange,
  onCancel,
  onSave,
}: {
  draft: LookupTable;
  isNew: boolean;
  busy: boolean;
  err: string | null;
  onChange: (next: LookupTable) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  return (
    <Panel>
      <div className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <span className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-accent">
            {isNew ? "New lookup table" : `Editing ${draft.id}`}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onCancel} disabled={busy}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" onClick={onSave} disabled={busy}>
              {busy ? "Saving…" : "Save lookup"}
            </Button>
          </div>
        </div>
        {err && <div className="font-mono text-[11.5px] text-red">{err}</div>}
        {isNew && (
          <input
            className="w-full bg-transparent border border-border rounded px-2 py-1 font-mono text-[12px]"
            value={draft.id}
            onChange={(e) => onChange({ ...draft, id: e.target.value })}
            placeholder="lookup_id"
          />
        )}
        <Field label="Name (optional)">
          <Input
            value={draft.name ?? ""}
            onChange={(e) => onChange({ ...draft, name: e.target.value || null })}
            placeholder="Country names"
          />
        </Field>
        <Field label="Default" hint="value used when no match">
          <Input
            value={draft.default ?? ""}
            onChange={(e) => onChange({ ...draft, default: e.target.value || null })}
            placeholder="OTHER"
          />
        </Field>
        <Field label="Mappings" hint="key on the left, replacement value on the right">
          <LookupMappingsEditor
            value={draft.mappings}
            onChange={(m) => onChange({ ...draft, mappings: m })}
          />
        </Field>
      </div>
    </Panel>
  );
}

export function LookupTablesTable() {
  const { data: rows = [], mutate } = useSWR<LookupTable[]>("/api/lookup-tables");
  const [editing, setEditing] = useState<{ draft: LookupTable; isNew: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const { can } = usePermissions();
  const canWrite = can("lookup_table:write");
  const canDelete = can("lookup_table:delete");
  const toast = useToast();

  const openNew = () => {
    setEditing({ draft: emptyLookup(`lookup_${rows.length + 1}`), isNew: true });
    setErr(null);
  };
  const openEdit = (row: LookupTable) => {
    setEditing({ draft: row, isNew: false });
    setErr(null);
  };
  const save = async () => {
    if (!editing) return;
    setBusy(true);
    setErr(null);
    try {
      if (editing.isNew) await createLookupTable(editing.draft);
      else await updateLookupTable(editing.draft.id, editing.draft);
      await mutate();
      setEditing(null);
    } catch (e) {
      const h = humanizeError(e, { action: "save", entity: "lookup table" });
      setErr(h.detail ? `${h.message} — ${h.detail}` : h.message);
    } finally {
      setBusy(false);
    }
  };
  const onBulkDelete = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (!confirm(`Delete ${ids.length} lookup table(s)?`)) return;
    setBulkBusy(true);
    try {
      const result: BulkDeleteResult = await bulkDeleteLookupTables(ids);
      toast.success({ title: summarizeBulkDelete("lookup table", result) });
      setSelectedIds(new Set());
      await mutate();
    } catch (e) {
      toast.error(humanizeError(e, { action: "delete", entity: "lookup tables" }));
    } finally {
      setBulkBusy(false);
    }
  };

  const selection: DataTableSelection<LookupTable> | undefined = canDelete
    ? {
        selectedIds,
        rowId: (r) => r.id,
        onToggle: (id) =>
          setSelectedIds((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
          }),
        onToggleAll: () =>
          setSelectedIds((prev) =>
            prev.size === rows.length ? new Set() : new Set(rows.map((r) => r.id)),
          ),
      }
    : undefined;

  const onDelete = async (id: string) => {
    if (!confirm(`Delete lookup table '${id}'?`)) return;
    setDeletingId(id);
    try {
      await deleteLookupTable(id);
      await mutate();
    } catch (e) {
      toast.error(humanizeError(e, { action: "delete", entity: "lookup table" }));
    } finally {
      setDeletingId(null);
    }
  };

  const columns: Column<LookupTable>[] = [
    {
      key: "id",
      header: "ID",
      width: "1.5fr",
      render: (r) => <span className="font-mono text-[12px]">{r.id}</span>,
    },
    {
      key: "name",
      header: "Name",
      width: "1.5fr",
      render: (r) => <span className="text-[12.5px]">{r.name ?? ""}</span>,
    },
    {
      key: "entries",
      header: "Entries",
      width: "90px",
      render: (r) => (
        <span className="font-mono text-[11.5px] text-muted">
          {Object.keys(r.mappings || {}).length}
        </span>
      ),
    },
    {
      key: "default",
      header: "Default",
      width: "1fr",
      render: (r) => (
        <span className="font-mono text-[11.5px] text-subtle truncate">
          {r.default ?? "—"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      width: "100px",
      align: "right",
      render: (r) => canDelete ? (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onDelete(r.id);
          }}
          disabled={deletingId === r.id}
          className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-red disabled:opacity-50"
        >
          {deletingId === r.id ? "…" : "Delete"}
        </button>
      ) : null,
    },
  ];

  return (
    <>
      <Topbar
        crumbs={[{ label: "Workspace", href: "/" }, { label: "Lookup tables" }]}
        actions={
          !editing && canWrite ? (
            <Button variant="primary" size="sm" kbd="N" onClick={openNew}>
              New lookup table
            </Button>
          ) : undefined
        }
      />
      <PageHeader
        title="Lookup tables"
        lede="Reusable key → value maps referenced by map/lookup steps across pipelines."
      />
      <div className="px-14 py-8">
        <div className="space-y-6">
          {editing ? (
            <LookupEditorPanel
              draft={editing.draft}
              isNew={editing.isNew}
              busy={busy}
              err={err}
              onChange={(d) => setEditing({ ...editing, draft: d })}
              onCancel={() => setEditing(null)}
              onSave={save}
            />
          ) : (
            <div className="flex flex-col gap-2">
              {canDelete && selectedIds.size > 0 && (
                <div className="flex items-center justify-between px-3.5 py-2 border border-border rounded-[var(--radius)] bg-surface-2">
                  <span className="font-mono text-[11px] text-muted">
                    {selectedIds.size} selected
                  </span>
                  <button
                    type="button"
                    onClick={onBulkDelete}
                    disabled={bulkBusy}
                    className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-red disabled:opacity-50"
                  >
                    {bulkBusy ? "Deleting…" : "Delete selected"}
                  </button>
                </div>
              )}
              <DataTable
                columns={columns}
                rows={rows}
                selection={selection}
                onRowClick={canWrite ? openEdit : undefined}
                emptyText="No lookup tables yet. Create one to reuse across map/lookup steps."
              />
            </div>
          )}
        </div>
      </div>
    </>
  );
}
