/**
 * One tile: a pipeline's preview rows, drawn (plan 064).
 *
 * Each tile fetches its own data. That is the reason there is no
 * `/dashboards/{id}/data` endpoint — a batched route would need its own
 * partial-failure shape, whereas per-tile SWR gives every tile an
 * independent loading, error and empty state for free. One broken pipeline
 * breaks one tile.
 */
import useSWR from "swr";
import { Panel, PanelHead } from "@/components/ui";
import { previewPipeline, type DashboardTile } from "@/lib/api";
import { Chart } from "./chart";

const HEIGHTS: Record<string, string> = {
  s: "h-[180px]",
  m: "h-[260px]",
  l: "h-[380px]",
};

function Note({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "red" }) {
  return (
    <div
      className={`h-full flex items-center justify-center px-4 text-center text-[12px] ${
        tone === "red" ? "text-red" : "text-subtle"
      }`}
    >
      {children}
    </div>
  );
}

export function Tile({ tile }: { tile: DashboardTile }) {
  const { data, error, isLoading } = useSWR(
    tile.pipeline_id ? ["tile-preview", tile.pipeline_id, tile.limit] : null,
    () => previewPipeline(tile.pipeline_id, tile.limit),
    // Charts are read, not watched. Revalidating on every window focus turns
    // a dashboard left open into a steady stream of pipeline executions.
    { revalidateOnFocus: false, keepPreviousData: true },
  );

  const body = () => {
    if (isLoading && !data) return <Note>Loading…</Note>;

    // A deleted pipeline is the expected failure here: tiles hold a
    // pipeline id inside JSONB, which Postgres cannot enforce as a foreign
    // key. Naming it beats a bare 404.
    if (error) {
      const status = (error as { status?: number })?.status;
      return (
        <Note tone="red">
          {status === 404
            ? "That pipeline no longer exists — edit this tile to point it somewhere else."
            : `Could not load rows: ${(error as Error).message}`}
        </Note>
      );
    }

    // A compile error comes back 200 with `error` set; it is the actionable
    // message (a bad expression, a missing column), so show it rather than
    // an empty chart.
    if (data?.error) return <Note tone="red">{data.error}</Note>;

    if (!data?.rows?.length) return <Note>This pipeline returned no rows.</Note>;

    return <Chart rows={data.rows} spec={tile.chart} />;
  };

  return (
    <Panel>
      <PanelHead label={tile.title} count={data?.rows?.length} />
      <div className={`${HEIGHTS[tile.height] ?? HEIGHTS.m} p-2`}>{body()}</div>
    </Panel>
  );
}
