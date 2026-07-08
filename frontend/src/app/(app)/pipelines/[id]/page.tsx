import Link from "next/link";
import { notFound } from "next/navigation";
import {
  Button,
  PageHeader,
  Panel,
  PanelHead,
  Item,
  Tag,
  Pill,
  SectionHead,
  DataTable,
  Topbar,
  type Column,
} from "@/components/ui";
import {
  getPipeline,
  listPipelineRuns,
  ApiError,
  type Run,
  type DltSource,
} from "@/lib/api";
import { TriggerButton } from "@/components/trigger-button";

export const dynamic = "force-dynamic";

type Params = Promise<{ id: string }>;

const RunPillFor = ({ status }: { status: Run["status"] }) => {
  const map: Record<Run["status"], "ok" | "running" | "failed" | "pending"> = {
    completed: "ok",
    running: "running",
    failed: "failed",
    pending: "pending",
  };
  return <Pill status={map[status]} />;
};

export default async function PipelineDetail({ params }: { params: Params }) {
  const { id } = await params;

  try {
    const pipeline = await getPipeline(id);
    const runs = await listPipelineRuns(id, 20).catch(() => [] as Run[]);

    const runsColumns: Column<Run>[] = [
      {
        key: "id",
        header: "Run",
        width: "220px",
        render: (r) => (
          <Link
            href={`/runs/${encodeURIComponent(r.id)}`}
            className="font-mono text-[12px] text-text hover:text-accent"
          >
            {r.id.slice(0, 8)}
          </Link>
        ),
      },
      {
        key: "status",
        header: "Status",
        width: "120px",
        render: (r) => <RunPillFor status={r.status} />,
      },
      {
        key: "rows",
        header: "Rows",
        width: "120px",
        render: (r) => (
          <span className="font-mono text-[12px] text-text tabular-nums">
            {r.rows_written ?? "—"}
          </span>
        ),
      },
      {
        key: "started",
        header: "Started",
        width: "220px",
        render: (r) => (
          <span className="font-mono text-[11.5px] text-subtle">
            {r.started_at ?? "—"}
          </span>
        ),
      },
      {
        key: "err",
        header: "Error",
        width: "1fr",
        render: (r) => (
          <span className="font-mono text-[11.5px] text-red truncate">
            {r.error ?? ""}
          </span>
        ),
      },
    ];

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
                  path={
                    (s.config as Record<string, unknown>)?.bucket_url as string ??
                    (s.config as Record<string, unknown>)?.connection_string as string ??
                    (s.config as Record<string, unknown>)?.connection_url as string ??
                    JSON.stringify(s.config)
                  }
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
            <SectionHead
              title="Recent runs"
              count={`· ${runs.length}`}
            />
            <DataTable
              columns={runsColumns}
              rows={runs}
              onRowClick={(r) => {
                if (typeof window !== "undefined") {
                  window.location.href = `/runs/${encodeURIComponent(r.id)}`;
                }
              }}
              emptyText="No runs yet — trigger one to get started."
            />
          </section>
        </div>
      </>
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
}
