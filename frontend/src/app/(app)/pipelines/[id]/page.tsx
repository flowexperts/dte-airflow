import Link from "next/link";
import { notFound } from "next/navigation";
import {
  Button,
  PageHeader,
  Panel,
  PanelHead,
  Item,
  Tag,
  SectionHead,
  Topbar,
} from "@/components/ui";
import {
  getPipeline,
  getSource,
  getDestination,
  listPipelineRuns,
  ApiError,
  type Run,
  type Source,
  type Destination,
} from "@/lib/api";
import { TriggerButton } from "@/components/trigger-button";
import { RunsTable } from "@/components/runs-table";
import { PipelinePreview } from "@/components/pipeline-preview";
import { HistoryPanel } from "@/components/builder/history/HistoryPanel";
import { SchedulePanel } from "@/components/builder/schedules/SchedulePanel";

export const revalidate = 30; // list/detail shell — SWR handles freshness client-side (P2 #26)

type Params = Promise<{ id: string }>;

function sourcePathLabel(s: Source): string {
  const cfg = (s.config as Record<string, unknown>) ?? {};
  return (
    (cfg.bucket_url as string) ??
    (cfg.connection_string as string) ??
    (cfg.connection_url as string) ??
    JSON.stringify(cfg)
  );
}

function destinationPathLabel(d: Destination): string {
  const c = d.config as Record<string, unknown>;
  return (c.path as string) ?? (c.bucket_url as string) ?? (c.table as string) ?? d.config.type;
}

export default async function PipelineDetail({ params }: { params: Params }) {
  const { id } = await params;

  try {
    const pipeline = await getPipeline(id);
    const [sources, destination, runs] = await Promise.all([
      Promise.all((pipeline.sources ?? []).map((sid) => getSource(sid).catch(() => null))),
      pipeline.output_id ? getDestination(pipeline.output_id).catch(() => null) : Promise.resolve(null),
      listPipelineRuns(id, 20).catch(() => [] as Run[]),
    ]);

    return (
      <>
        <Topbar
          crumbs={[
            { label: "Workspace", href: "/" },
            { label: "Pipelines", href: "/pipelines" },
            { label: pipeline.name },
          ]}
          actions={
            <>
              <Link href={`/pipelines/${encodeURIComponent(pipeline.id)}/edit`}>
                <Button size="sm">Edit</Button>
              </Link>
              <TriggerButton pipelineId={pipeline.id} params={pipeline.params} />
            </>
          }
        />

        <PageHeader
          title={pipeline.name}
          sub={pipeline.id}
          lede={`${pipeline.sources?.length ?? 0} source${(pipeline.sources?.length ?? 0) === 1 ? "" : "s"} · ${pipeline.steps?.length ?? 0} step${(pipeline.steps?.length ?? 0) === 1 ? "" : "s"} · output → ${destination ? destinationPathLabel(destination) : pipeline.output_id}`}
        />

        <div className="px-14 py-8 space-y-8">
          <div className="grid grid-cols-2 gap-5">
            <Panel>
              <PanelHead label="Sources" count={pipeline.sources?.length ?? 0} />
              {sources.map((s, i) =>
                s ? (
                  <Item
                    key={s.id}
                    glyph="§"
                    label={s.id}
                    path={sourcePathLabel(s)}
                    tag={<Tag>{s.source_type}</Tag>}
                  />
                ) : (
                  <Item
                    key={pipeline.sources?.[i] ?? String(i)}
                    glyph="§"
                    label={pipeline.sources?.[i] ?? "?"}
                    path="(source not found)"
                    tag={<Tag>missing</Tag>}
                  />
                ),
              )}
            </Panel>
            <Panel>
              <PanelHead label="Output" count={1} />
              {destination ? (
                <Item
                  glyph="¶"
                  label={destination.id}
                  path={destinationPathLabel(destination)}
                  tag={<Tag variant="output">{destination.config.type}</Tag>}
                />
              ) : (
                <Item
                  glyph="¶"
                  label={pipeline.output_id}
                  path="(destination not found)"
                  tag={<Tag variant="output">missing</Tag>}
                />
              )}
            </Panel>
          </div>

          <PipelinePreview pipelineId={pipeline.id} />

          <SchedulePanel pipelineId={pipeline.id} pipelineParams={pipeline.params} />

          <section>
            <SectionHead title="Recent runs" count={`· ${runs.length}`} />
            <RunsTable runs={runs} />
          </section>

          <section>
            <SectionHead title="History" />
            <HistoryPanel pipelineId={pipeline.id} />
          </section>
        </div>
      </>
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}
