import useSWR from "swr";
import { Panel, PanelHead, Tag } from "@/components/ui";
import { diffPipelineRevisions, type StepChange } from "@/lib/api";

/**
 * Renders the server-side diff between two revisions of the same
 * pipeline. Whole-step comparison (matches backend); no per-key
 * highlighting inside a step.
 */
export function DiffView({
  pipelineId,
  fromId,
  toId,
}: {
  pipelineId: string;
  fromId: string;
  toId: string;
}) {
  const { data, error, isLoading } = useSWR(
    ["pipeline-diff", pipelineId, fromId, toId],
    () => diffPipelineRevisions(pipelineId, fromId, toId),
  );

  if (isLoading) {
    return <div className="text-[12px] text-subtle px-3 py-4">Loading diff…</div>;
  }
  if (error) {
    return (
      <div className="text-[12px] text-red px-3 py-4">
        Couldn&apos;t load diff.
      </div>
    );
  }
  if (!data) return null;
  const { diff, summary } = data;

  return (
    <Panel>
      <PanelHead label="Diff" count={summary} />
      <div className="px-3.5 py-3 space-y-4 text-[13px]">
        {diff.name_changed && (
          <ChangeRow
            label="name"
            before={diff.name_before ?? "(none)"}
            after={diff.name_after ?? "(none)"}
          />
        )}
        {(diff.sources_added.length > 0 || diff.sources_removed.length > 0) && (
          <div>
            <div className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle mb-1">
              sources
            </div>
            {diff.sources_added.map((s) => (
              <div key={`+${s}`} className="font-mono text-[12px] text-green">+ {s}</div>
            ))}
            {diff.sources_removed.map((s) => (
              <div key={`-${s}`} className="font-mono text-[12px] text-red">- {s}</div>
            ))}
          </div>
        )}
        {diff.output_id_changed && (
          <ChangeRow
            label="output_id"
            before={diff.output_id_before ?? "(none)"}
            after={diff.output_id_after ?? "(none)"}
          />
        )}
        {diff.steps.length > 0 && (
          <div className="space-y-2">
            <div className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle">
              steps
            </div>
            {diff.steps.map((s) => (
              <StepDiffRow key={`${s.index}-${s.kind}`} step={s} />
            ))}
          </div>
        )}
        {!diff.name_changed &&
          diff.sources_added.length === 0 &&
          diff.sources_removed.length === 0 &&
          !diff.output_id_changed &&
          diff.steps.length === 0 && (
            <div className="text-[12px] text-subtle">No structural changes.</div>
          )}
      </div>
    </Panel>
  );
}

function ChangeRow({
  label,
  before,
  after,
}: {
  label: string;
  before: string;
  after: string;
}) {
  return (
    <div>
      <div className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle mb-1">
        {label}
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div className="font-mono text-[12px] bg-code-bg px-2 py-1 rounded-sm text-red line-through">
          {before}
        </div>
        <div className="font-mono text-[12px] bg-code-bg px-2 py-1 rounded-sm text-green">
          {after}
        </div>
      </div>
    </div>
  );
}

function StepDiffRow({ step }: { step: StepChange }) {
  const kindColor =
    step.kind === "added" ? "text-green" : step.kind === "removed" ? "text-red" : "text-gold";
  return (
    <div className="border border-border rounded-sm p-2 space-y-2">
      <div className="flex items-center gap-2 text-[11.5px]">
        <span className="font-mono text-subtle">step {step.index}</span>
        <Tag>{step.op}</Tag>
        <span className={`font-mono ${kindColor}`}>{step.kind}</span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <pre className="font-mono text-[11px] bg-code-bg p-2 rounded-sm whitespace-pre-wrap overflow-x-auto">
          {step.before ? JSON.stringify(step.before, null, 2) : "(added)"}
        </pre>
        <pre className="font-mono text-[11px] bg-code-bg p-2 rounded-sm whitespace-pre-wrap overflow-x-auto">
          {step.after ? JSON.stringify(step.after, null, 2) : "(removed)"}
        </pre>
      </div>
    </div>
  );
}
