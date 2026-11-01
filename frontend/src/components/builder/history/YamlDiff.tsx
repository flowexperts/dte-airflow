import { Fragment, useState } from "react";
import useSWR from "swr";
import { Panel, PanelHead, Tabs } from "@/components/ui";
import { cn } from "@/lib/cn";
import {
  diffPipelineRevisions,
  listPipelineRevisions,
  type PipelineRevision,
  type RevisionDiffResponse,
  type YamlDiffRow,
} from "@/lib/api";

const MONO = "font-mono text-[11.5px] leading-[1.55]";
const NOTE = "text-[12px] text-subtle px-3.5 py-3";

/**
 * Before | after, line-paired by the backend (`difflib`). One grid row per
 * pair, so a wrapped line on either side keeps both sides aligned — two
 * independently scrolling `<pre>`s drift apart. Unchanged runs between hunks
 * collapse to a `⋯` row.
 */
function SplitDiff({ data }: { data: RevisionDiffResponse }) {
  if (data.yaml_diff.length === 0) return <div className={NOTE}>No changes.</div>;
  const head = (r: RevisionDiffResponse["from"]) =>
    `${r.id.slice(0, 8)}${r.changed_at ? ` · ${new Date(r.changed_at).toLocaleString()}` : ""}`;
  return (
    <div className={cn(MONO, "grid grid-cols-[auto_minmax(0,1fr)_auto_minmax(0,1fr)]")}>
      <div className="col-span-2 px-3 py-1.5 text-subtle border-b border-border">
        {head(data.from)}
      </div>
      <div className="col-span-2 px-3 py-1.5 text-subtle border-b border-l border-border">
        {head(data.to)}
      </div>
      {data.yaml_diff.map((hunk, h) => (
        <Fragment key={h}>
          {h > 0 && <div className="col-span-4 px-3 text-subtle bg-surface-2 select-none">⋯</div>}
          {hunk.map((row, i) => (
            <Row key={i} row={row} />
          ))}
        </Fragment>
      ))}
    </div>
  );
}

function Row({ row }: { row: YamlDiffRow }) {
  const changed = row.kind !== "equal";
  const side = (no: number | null, text: string | null, tone: string, left: boolean) => (
    <>
      <span
        className={cn(
          "px-2 text-right text-subtle select-none",
          !left && "border-l border-border",
          text === null ? "bg-surface-2" : changed && tone,
        )}
      >
        {no ?? ""}
      </span>
      <span
        className={cn(
          "pr-3 whitespace-pre-wrap break-all",
          text === null ? "bg-surface-2" : changed && tone,
        )}
      >
        {text ?? ""}
      </span>
    </>
  );
  return (
    <>
      {side(row.a_no, row.a, "bg-red-tint", true)}
      {side(row.b_no, row.b, "bg-green-tint", false)}
    </>
  );
}

/**
 * The revision as the YAML file `dte export` / file mode would write, and
 * a split diff against the revision before it. Sits beside the read-only
 * spec on a revision page.
 */
/** The diff from the revision before this one; `null` for the first.
 *  Shared by the canvas step marks and the Changes tab (one SWR key, one
 *  request). */
export function usePrevDiff(revision: PipelineRevision | undefined) {
  // ponytail: predecessor found in the newest 100 revisions; older ones
  // show "initial" — add a `previous_id` on the revision GET if that bites.
  return useSWR(
    revision ? ["revision-prev-diff", revision.pipeline_id, revision.id] : null,
    async () => {
      const revs = await listPipelineRevisions(revision!.pipeline_id);
      const prev = revs[revs.findIndex((r) => r.id === revision!.id) + 1];
      return prev ? diffPipelineRevisions(revision!.pipeline_id, prev.id, revision!.id) : null;
    },
  ).data;
}

export function RevisionYaml({ revision }: { revision: PipelineRevision }) {
  const [view, setView] = useState<"changes" | "yaml">("changes");
  const diff = usePrevDiff(revision);

  return (
    <Panel>
      <PanelHead label={`${revision.pipeline_id}.yaml`} />
      <Tabs
        value={view}
        onChange={setView}
        options={[
          { value: "changes", label: "Changes" },
          { value: "yaml", label: "YAML" },
        ]}
        className="px-3.5"
      />
      {view === "yaml" ? (
        <pre className={cn(MONO, "px-3.5 py-3 overflow-x-auto")}>{revision.yaml}</pre>
      ) : diff === undefined ? (
        <div className={NOTE}>Loading diff…</div>
      ) : diff === null ? (
        <div className={NOTE}>Initial revision — nothing to compare against.</div>
      ) : (
        <SplitDiff data={diff} />
      )}
    </Panel>
  );
}
