"use client";

import { use } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import useSWR from "swr";
import { InlineError, PageHeader, Panel, Topbar } from "@/components/ui";
import { ComparisonGrid } from "@/components/evals/comparison-grid";
import { getPipeline, type Pipeline } from "@/lib/api";

/**
 * `/pipelines/{id}/compare?sweep=<id>` — several configs, side by side.
 *
 * Lives under the pipeline rather than under an eval set because that is
 * where the user started. The eval set exists (it is what the scores hang
 * off) but it is derived, and nobody has to meet it to read this page.
 *
 * Client component: the grid polls while the sweep fills in, and the sweep
 * id arrives as a query param.
 */
export default function ComparePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const sweepId = useSearchParams().get("sweep");

  const { data: pipeline, error } = useSWR<Pipeline>(["pipeline", id], () => getPipeline(id));

  return (
    <>
      <Topbar
        crumbs={[
          { label: "Workspace", href: "/" },
          { label: "Pipelines", href: "/pipelines" },
          { label: pipeline?.name ?? id, href: `/pipelines/${encodeURIComponent(id)}` },
          { label: "Compare" },
        ]}
      />
      {/* Outside the padded body: PageHeader carries its own `px-14 py-6`
          and a full-bleed bottom border. Nesting it inside applied the
          inset twice and pushed the title off every other page's baseline. */}
      <PageHeader
        title="Compare configs"
        lede={
          "The same documents, extracted several ways. Disagreements sort first — " +
          "they are the ones worth reading, and the ones worth labelling."
        }
      />

      <div className="px-14 py-8 flex flex-col gap-6">
        {error && <InlineError message="Could not load this pipeline." />}

        {!sweepId ? (
          // Reachable by typing the URL or bookmarking mid-flow. Say what is
          // missing and how to get one rather than rendering an empty grid.
          <Panel>
            <div className="px-4 py-4 text-[12.5px] text-muted">
              No comparison selected. Open{" "}
              <Link
                href={`/pipelines/${encodeURIComponent(id)}`}
                className="text-text underline underline-offset-2"
              >
                the pipeline
              </Link>{" "}
              and choose <strong className="text-text">Compare…</strong> to run one.
            </div>
          </Panel>
        ) : (
          <ComparisonGrid sweepId={sweepId} />
        )}
      </div>
    </>
  );
}
