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
  listPipelineRuns,
  ApiError,
  type Run,
  type DltSource,
} from "@/lib/api";
import { TriggerButton } from "@/components/trigger-button";
import { RunsTable } from "@/components/runs-table";

export const dynamic = "force-dynamic";

type Params = Promise<{ id: string }>;

function sourcePathLabel(s: DltSource): string {
  const cfg = (s.config as Record<string, unknown>) ?? {};
  return (
    (cfg.bucket_url as string) ??
    (cfg.connection_string as string) ??
    (cfg.connection_url as string) ??
    JSON.stringify(cfg)
  );
}

export default async function PipelineDetail({ params }: { params: Params }) {
  const { id } = await params;

  try {
    const pipeline = await getPipeline(id);
    const runs = await listPipelineRuns(id, 20).catch(() => [] as Run[]);

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
              <TriggerButton pipelineId={pipeline.id} />
            </>
          }
        />

        <PageHeader
          title={pipeline.name}
          sub={pipeline.id}
          lede={`${pipeline.sources?.length ?? 0} source${(pipeline.sources?.length ?? 0) === 1 ? "" : "s"} · ${pipeline.steps?.length ?? 0} step${(pipeline.steps?.length ?? 0) === 1 ? "" : "s"} · output → ${pipeline.output?.path}`}
        />

        <div className="px-14 py-8 space-y-8">
          <div className="grid grid-cols-2 gap-5">
            <Panel>
              <PanelHead label="Sources" count={pipeline.sources?.length ?? 0} />
              {(pipeline.sources ?? []).map((s: DltSource) => (
                <Item
                  key={s.id}
                  glyph="§"
                  label={s.id}
                  path={sourcePathLabel(s)}
                  tag={<Tag>{s.source_type}</Tag>}
                />
              ))}
            </Panel>
            <Panel>
              <PanelHead label="Output" count={1} />
              <Item
                glyph="¶"
                label="output"
                path={pipeline.output?.path}
                tag={<Tag variant="output">{pipeline.output?.type}</Tag>}
              />
            </Panel>
          </div>

          <section>
            <SectionHead title="Recent runs" count={`· ${runs.length}`} />
            <RunsTable runs={runs} />
          </section>
        </div>
      </>
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}
