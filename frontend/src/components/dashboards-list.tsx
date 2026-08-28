"use client";

/**
 * The dashboards list, with an inline creator (plan 064).
 *
 * Page chrome follows the same three-part shape as every other list surface
 * (`sources/page.tsx`, `lookup-tables-table.tsx`): a sticky `Topbar` of
 * crumbs, a full-bleed `PageHeader`, then the body inside `px-14 py-8`.
 * `Topbar` and `PageHeader` carry their own `px-14`; only the body needs it
 * — without that box the table sits flush against the sidebar while every
 * neighbouring page is inset.
 *
 * Creation lives here beside the thing being added, not in the nav — the
 * same rule `app-sidebar.tsx` states for pipelines. A new dashboard is
 * name-only: tiles are added on its own page, where the charts they
 * describe are visible while you configure them.
 */
import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import {
  Button,
  DataTable,
  Field,
  InlineError,
  Input,
  PageHeader,
  Panel,
  Topbar,
  type Column,
} from "@/components/ui";
import { createDashboard, deleteDashboard, type Dashboard } from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";
import { humanizeError, type HumanError } from "@/lib/errors";

export function DashboardsList() {
  const { data, isLoading, mutate } = useSWR<Dashboard[]>("/api/dashboards");
  const { can, isLoading: permsLoading } = usePermissions();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<HumanError | null>(null);

  // Show while permissions are in flight: `can()` reads an empty list until
  // /api/auth/me resolves, so gating on it alone hides the primary action on
  // first paint — and permanently if that request fails. Mirrors
  // `NewResourceButton`. The server still authorises the actual write.
  const mayWrite = permsLoading || can("dashboard:write");
  const mayDelete = permsLoading || can("dashboard:delete");

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await createDashboard({ name, description: null, tiles: [] });
      setName("");
      setCreating(false);
      await mutate();
    } catch (e) {
      setErr(humanizeError(e, { entity: "dashboard", action: "save" }));
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
    {
      key: "tiles",
      header: "Tiles",
      width: "100px",
      render: (d) => <span className="tabular-nums">{d.tiles?.length ?? 0}</span>,
    },
    {
      key: "description",
      header: "Description",
      render: (d) => <span className="text-muted">{d.description ?? "—"}</span>,
    },
    {
      key: "actions",
      header: "",
      width: "90px",
      align: "right",
      render: (d) =>
        mayDelete ? (
          <Button variant="ghost" size="sm" onClick={() => remove(d.id)}>
            Delete
          </Button>
        ) : null,
    },
  ];

  return (
    <>
      <Topbar
        crumbs={[{ label: "Workspace", href: "/" }, { label: "Dashboards" }]}
        actions={
          mayWrite && !creating ? (
            <Button variant="primary" size="sm" onClick={() => setCreating(true)}>
              New dashboard
            </Button>
          ) : null
        }
      />
      <PageHeader
        title="Dashboards"
        {...(data ? { sub: `${data.length} total` } : {})}
        lede="Charts drawn from pipeline output. A tile reads its pipeline's rows directly — nothing is written anywhere."
      />

      <div className="px-14 py-8 space-y-6">
        {creating && (
          <Panel>
            <div className="p-4 space-y-3">
              {err && (
                <InlineError title={err.title} message={err.message} detail={err.detail} />
              )}
              <Field label="Name" hint="editable; unique per workspace">
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Sales overview"
                />
              </Field>
              <div className="flex items-center gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={save}
                  disabled={busy || !name.trim()}
                >
                  {busy ? "Saving…" : "Create dashboard"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setCreating(false)}
                  disabled={busy}
                >
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
    </>
  );
}
