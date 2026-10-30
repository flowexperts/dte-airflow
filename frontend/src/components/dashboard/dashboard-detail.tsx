/**
 * One dashboard: the grid, plus an edit mode over the same grid (plan 064).
 *
 * Editing happens **in place** rather than on a separate route, because the
 * thing being configured is the chart you are looking at. A tile's field
 * pickers are only meaningful next to the plot they change; on a separate
 * page you would be picking column names blind and round-tripping to check.
 */
import { useState } from "react";
import useSWR from "swr";
import { Button, InlineError, PageHeader, Topbar } from "@/components/ui";
import { getDashboard, updateDashboard, type Dashboard, type DashboardTile } from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";
import { humanizeError, type HumanError } from "@/lib/errors";
import { DashboardGrid } from "./grid";
import { TileEditor } from "./tile-editor";

const CRUMBS_BASE = [
  { label: "Workspace", href: "/" },
  { label: "Dashboards", href: "/dashboards" },
];

function emptyTile(n: number): DashboardTile {
  return {
    // Blank means server-generated, the same convention every other entity
    // uses (`_blank_id_means_generate`).
    id: "",
    title: `Tile ${n}`,
    pipeline_id: "",
    chart: { kind: "bar", x: null, y: [], series: null, stacked: false },
    width: 6,
    height: "m",
    limit: 1000,
  };
}

export function DashboardDetail({ id }: { id: string }) {
  const { data, error, isLoading, mutate } = useSWR<Dashboard>(`dashboard-${id}`, () =>
    getDashboard(id),
  );
  const { can, isLoading: permsLoading } = usePermissions();
  const [draft, setDraft] = useState<DashboardTile[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [saveErr, setSaveErr] = useState<HumanError | null>(null);

  if (error) {
    const e = humanizeError(error, { entity: "dashboard", action: "load" });
    return (
      <>
        <Topbar crumbs={CRUMBS_BASE} />
        <div className="px-14 py-8">
          <InlineError title={e.title} message={e.message} detail={e.detail} />
        </div>
      </>
    );
  }
  if (isLoading || !data) {
    return (
      <>
        <Topbar crumbs={CRUMBS_BASE} />
        <div className="px-14 py-8 text-[12.5px] text-subtle">Loading…</div>
      </>
    );
  }

  // See dashboards-list: `can()` is empty until /api/me resolves.
  const mayWrite = permsLoading || can("dashboard:write");
  const editing = draft !== null;
  const tiles = draft ?? data.tiles ?? [];

  const setTile = (i: number, next: DashboardTile) =>
    setDraft(tiles.map((t, j) => (j === i ? next : t)));

  const move = (i: number, delta: -1 | 1) => {
    const j = i + delta;
    if (j < 0 || j >= tiles.length) return;
    const next = [...tiles];
    // Swap, not splice-and-insert: the grid renders in array order, so a
    // swap is the whole operation.
    [next[i], next[j]] = [next[j]!, next[i]!];
    setDraft(next);
  };

  const save = async () => {
    setBusy(true);
    setSaveErr(null);
    try {
      await updateDashboard(id, { ...data, tiles });
      setDraft(null);
      await mutate();
    } catch (e) {
      setSaveErr(humanizeError(e, { entity: "dashboard", action: "save" }));
    } finally {
      setBusy(false);
    }
  };

  const actions = mayWrite ? (
    editing ? (
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setDraft([...tiles, emptyTile(tiles.length + 1)])}
        >
          + Add tile
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setDraft(null)} disabled={busy}>
          Cancel
        </Button>
        <Button variant="primary" size="sm" onClick={save} disabled={busy}>
          {busy ? "Saving\u2026" : "Save layout"}
        </Button>
      </div>
    ) : (
      <Button variant="primary" size="sm" onClick={() => setDraft([...(data.tiles ?? [])])}>
        Edit
      </Button>
    )
  ) : null;

  return (
    <>
      {/* Same chrome as every other detail surface: crumbs, then a
          full-bleed header, then the body inset by px-14. The action
          buttons ride the Topbar rather than the PageHeader so their
          position does not shift when the description wraps. */}
      <Topbar crumbs={[...CRUMBS_BASE, { label: data.name }]} actions={actions} />
      <PageHeader
        title={data.name}
        sub={`${tiles.length} ${tiles.length === 1 ? "tile" : "tiles"}`}
        {...(data.description ? { lede: data.description } : {})}
      />

      <div className="px-14 py-8 space-y-6">
        {saveErr && (
          <InlineError title={saveErr.title} message={saveErr.message} detail={saveErr.detail} />
        )}

        <DashboardGrid
          tiles={tiles}
          {...(editing
            ? {
                renderOverlay: (tile: DashboardTile, i: number) => (
                  <div className="mb-2">
                    <TileEditor
                      tile={tile}
                      onChange={(next) => setTile(i, next)}
                      onRemove={() => setDraft(tiles.filter((_, j) => j !== i))}
                      onMove={(d) => move(i, d)}
                    />
                  </div>
                ),
              }
            : {})}
        />
      </div>
    </>
  );
}
