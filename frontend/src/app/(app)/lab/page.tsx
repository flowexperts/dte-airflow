import Link from "next/link";
import { PageHeader, Panel, PanelHead, Topbar, Item, Tag } from "@/components/ui";
import { listPipelines, type Pipeline } from "@/lib/api";
import { isQualityPipeline, pipelineShape } from "./_lib";

export const dynamic = "force-dynamic";

const VARIATIONS = [
  {
    surface: "List",
    href: "/lab/pipelines",
    variants: [
      ["a", "Health-first table", "Last run, type, and a 5-run trend at the row. Health stops being a place you navigate to."],
      ["b", "Grouped cards", "Transform and quality as peer sections, verdict on the card face."],
    ],
  },
  {
    surface: "Detail",
    href: "/lab/pipelines",
    needsPipeline: true,
    variants: [
      ["a", "Unified canvas", "Steps readable inline, edit in place, run rail on the right. The debug loop costs zero navigations."],
      ["b", "Three-column console", "Outline · selected node · preview. Never scrolls, one extra click per step."],
      ["c", "Flow ribbon", "source → step → step → output as the navigation. Best at conveying shape."],
    ],
  },
];

export default async function LabIndex() {
  let pipelines: Pipeline[] = [];
  let error: string | null = null;
  try {
    pipelines = await listPipelines();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const transform = pipelines.filter((p) => !isQualityPipeline(p)).slice(0, 5);
  const quality = pipelines.filter(isQualityPipeline).slice(0, 5);

  return (
    <>
      <Topbar crumbs={[{ label: "Workspace", href: "/" }, { label: "Lab" }]} />
      <PageHeader
        title="Lab"
        sub="pipeline IA"
        lede="Layout variations running against your real backend. Flip between them with the Layout bar on each page; the existing /pipelines tree is untouched for comparison."
      />

      <div className="px-14 py-8 space-y-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
          {VARIATIONS.map((group) => (
            <Panel key={group.surface}>
              <PanelHead
                label={group.surface}
                count={
                  group.needsPipeline ? (
                    <span className="text-subtle">pick a pipeline below</span>
                  ) : (
                    <Link href={group.href} className="text-accent no-underline hover:underline">
                      open →
                    </Link>
                  )
                }
              />
              {group.variants.map(([v, name, note]) => (
                <div
                  key={v}
                  className="px-3.5 py-3 border-b border-border last:border-b-0"
                >
                  <div className="flex items-baseline gap-2.5">
                    <span className="font-mono text-[10px] font-bold tracking-[0.15em] uppercase text-accent px-1.5 py-0.5 rounded-sm bg-[color:var(--accent-tint)]">
                      {v}
                    </span>
                    <span className="text-[14px] font-medium">{name}</span>
                  </div>
                  <p className="text-[12.5px] text-muted mt-1 mb-0">{note}</p>
                </div>
              ))}
            </Panel>
          ))}
        </div>

        {error ? (
          <Panel>
            <PanelHead label="Backend unreachable" />
            <div className="px-4 py-4 font-mono text-[12.5px] text-red">{error}</div>
          </Panel>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
            <Panel>
              <PanelHead label="Your transform pipelines" count={transform.length} />
              {transform.length === 0 ? (
                <div className="px-4 py-4 text-sm text-subtle">
                  None yet — create one in the main app, then come back.
                </div>
              ) : (
                transform.map((p) => (
                  <Link
                    key={p.id}
                    href={`/lab/pipelines/${encodeURIComponent(p.id)}`}
                    className="block no-underline text-text"
                  >
                    <Item
                      glyph="§"
                      label={p.name}
                      path={pipelineShape(p)}
                      tag={<Tag>transform</Tag>}
                    />
                  </Link>
                ))
              )}
            </Panel>
            <Panel>
              <PanelHead label="Your quality pipelines" count={quality.length} />
              {quality.length === 0 ? (
                <div className="px-4 py-4 text-sm text-subtle">
                  None yet. The quality layouts are the ones most worth testing —
                  the current detail page renders them as a missing destination.
                </div>
              ) : (
                quality.map((p) => (
                  <Link
                    key={p.id}
                    href={`/lab/pipelines/${encodeURIComponent(p.id)}`}
                    className="block no-underline text-text"
                  >
                    <Item
                      glyph="✓"
                      label={p.name}
                      path={pipelineShape(p)}
                      tag={<Tag variant="output">quality</Tag>}
                    />
                  </Link>
                ))
              )}
            </Panel>
          </div>
        )}
      </div>
    </>
  );
}
