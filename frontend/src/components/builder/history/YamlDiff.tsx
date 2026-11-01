import { useState } from "react";
import useSWR from "swr";
import { Panel, PanelHead, Tabs } from "@/components/ui";
import { diffPipelineRevisions, listPipelineRevisions, type PipelineRevision } from "@/lib/api";

const PRE = "font-mono text-[11.5px] leading-[1.55] px-3.5 py-3 overflow-x-auto";

/** A unified diff (the backend's `difflib` output), one line per row,
 *  coloured by its prefix. The `---`/`+++` header lines are dropped. */
export function YamlDiff({ diff }: { diff: string }) {
  const lines = diff.split("\n").filter((l) => !l.startsWith("---") && !l.startsWith("+++"));
  if (!diff) return <div className="text-[12px] text-subtle px-3.5 py-3">No changes.</div>;
  return (
    <pre className={PRE}>
      {lines.map((l, i) => (
        <div
          key={i}
          className={
            l.startsWith("+")
              ? "text-green"
              : l.startsWith("-")
                ? "text-red"
                : l.startsWith("@@")
                  ? "text-subtle"
                  : ""
          }
        >
          {l || " "}
        </div>
      ))}
    </pre>
  );
}

/**
 * The revision as the YAML file `dte export` / file mode would write, and
 * its diff against the revision before it. Sits in the canvas rail slot on a
 * revision page, beside the read-only spec.
 */
export function RevisionYaml({ revision }: { revision: PipelineRevision }) {
  const [view, setView] = useState<"yaml" | "changes">("yaml");
  // ponytail: predecessor found in the newest 100 revisions; older ones
  // show "initial" — add a `previous_id` on the revision GET if that bites.
  const { data: diff } = useSWR(
    view === "changes" ? ["revision-prev-diff", revision.pipeline_id, revision.id] : null,
    async () => {
      const revs = await listPipelineRevisions(revision.pipeline_id);
      const prev = revs[revs.findIndex((r) => r.id === revision.id) + 1];
      return prev ? diffPipelineRevisions(revision.pipeline_id, prev.id, revision.id) : null;
    },
  );

  return (
    <Panel>
      <PanelHead label={`${revision.pipeline_id}.yaml`} />
      <Tabs
        value={view}
        onChange={setView}
        options={[
          { value: "yaml", label: "YAML" },
          { value: "changes", label: "Changes" },
        ]}
        className="px-3.5"
      />
      {view === "yaml" ? (
        <pre className={PRE}>{revision.yaml}</pre>
      ) : diff === undefined ? (
        <div className="text-[12px] text-subtle px-3.5 py-3">Loading diff…</div>
      ) : diff === null ? (
        <div className="text-[12px] text-subtle px-3.5 py-3">Initial revision.</div>
      ) : (
        <YamlDiff diff={diff.yaml_diff} />
      )}
    </Panel>
  );
}
