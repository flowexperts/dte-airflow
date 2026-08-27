"use client";

/**
 * The dashboards list, with an inline creator (plan 064).
 *
 * Creation lives on the list page beside the thing being added, not in the
 * nav — the same rule `app-sidebar.tsx` states for pipelines. A new
 * dashboard is name-only: tiles are added on its own page, where the charts
 * they describe are visible while you configure them.
 */
import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { Button, DataTable, Field, Input, PageHeader, Panel, type Column } from "@/components/ui";
import { createDashboard, deleteDashboard, type Dashboard } from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";
import { humanizeError } from "@/lib/errors";

export function DashboardsList() {
  const { data, isLoading, mutate } = useSWR<Dashboard[]>("/api/dashboards");
  const { can } = usePermissions();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await createDashboard({ name, description: null, tiles: [] });
      setName("");
      setCreating(false);
      await mutate();
    } catch (e) {
      setErr(humanizeError(e, { entity: "dashboard", action: "save" }).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    await deleteDashboard(id);
    await mutate();
  };

  const columns: Column<Dashboard>[] = [
    {
      key: "name",
      header: "Name",
      render: (d) => (
        <Link href={`/dashboards/${encodeURIComponent(d.id)}`} className="text-text">
          {d.name}
        </Link>
      ),
    },
    { key: "tiles", header: "Tiles", render: (d) => String(d.tiles?.length ?? 0) },
    {
      key: "actions",
      header: "",
      render: (d) =>
        can("dashboard:delete") ? (
          <Button variant="ghost" size="sm" onClick={() => remove(d.id)}>
            Delete
          </Button>
        ) : null,
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Dashboards"
        lede="Charts drawn from pipeline output. A tile reads its pipeline's rows directly — nothing is written anywhere."
        actions={
          can("dashboard:write") && !creating ? (
            <Button variant="primary" size="sm" onClick={() => setCreating(true)}>
              + New dashboard
            </Button>
          ) : null
        }
      />

      {creating && (
        <Panel>
          <div className="p-4 space-y-3">
            {err && <div className="font-mono text-[11.5px] text-red">{err}</div>}
            <Field label="Name" hint="unique per workspace">
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Orders overview"
              />
            </Field>
            <div className="flex items-center gap-2">
              <Button variant="primary" size="sm" onClick={save} disabled={busy || !name.trim()}>
                {busy ? "Saving…" : "Create"}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setCreating(false)} disabled={busy}>
                Cancel
              </Button>
            </div>
          </div>
        </Panel>
      )}

      <DataTable<Dashboard>
        rows={data ?? []}
        columns={columns}
        emptyText={isLoading ? "Loading…" : "No dashboards yet."}
      />
    </div>
  );
}
