import { useState } from "react";
import useSWR from "swr";
import { Button, InlineError, Panel, PanelHead, Textarea } from "@/components/ui";
import {
  importEvalExamples,
  listEvalExamples,
  type EvalExample,
  type EvalSet,
} from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";
import { useToast } from "@/components/toaster";
import { humanizeError } from "@/lib/errors";

const PAGE = 50;

/**
 * The labeled corpus.
 *
 * `label_source` is shown on every row rather than aggregated away: knowing a
 * label came from a model instead of a person is exactly what you need when
 * the scores look suspiciously good, and it is unrecoverable once hidden.
 */
export function ExamplesPanel({ evalSet }: { evalSet: EvalSet }) {
  const [offset, setOffset] = useState(0);
  const { can } = usePermissions();
  const { data, error, mutate } = useSWR(
    ["eval-examples", evalSet.id, offset],
    () => listEvalExamples(evalSet.id, { limit: PAGE, offset }),
  );

  if (error) {
    return <InlineError title="Couldn't load labels" message="The examples for this set didn't come back." />;
  }

  const rows = data?.examples ?? [];
  const total = data?.total ?? 0;
  const fields = evalSet.field_specs.map((f) => f.name);

  return (
    <div className="flex flex-col gap-6">
      {can("eval:write") && <ImportBox evalSetId={evalSet.id} onDone={() => void mutate()} />}

      <Panel>
        <PanelHead label="Labeled documents" count={total} />
        {rows.length === 0 ? (
          <div className="px-4 py-8 text-[13px] text-muted">
            No labels yet. Import a CSV above, or label documents from a run&apos;s
            output — reviewing and labeling are the same action.
          </div>
        ) : (
          rows.map((ex) => <ExampleRow key={ex.id} example={ex} fields={fields} />)
        )}
        {total > PAGE && (
          <div className="flex items-center justify-between px-4 py-2.5 border-t border-border">
            <Button
              variant="ghost"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE))}
            >
              Previous
            </Button>
            <span className="font-mono text-[11.5px] text-subtle tabular-nums">
              {offset + 1}–{Math.min(offset + PAGE, total)} of {total}
            </span>
            <Button
              variant="ghost"
              size="sm"
              disabled={offset + PAGE >= total}
              onClick={() => setOffset(offset + PAGE)}
            >
              Next
            </Button>
          </div>
        )}
      </Panel>
    </div>
  );
}

const SOURCE_TONE: Record<string, string> = {
  human: "var(--green)",
  consensus: "var(--accent)",
  imported: "var(--muted)",
  // Judge labels are the one source that can flatter a score, so they are the
  // one source rendered as a caution rather than a neutral fact.
  judge: "var(--gold)",
};

function ExampleRow({ example, fields }: { example: EvalExample; fields: string[] }) {
  return (
    <div className="border-b border-border last:border-b-0 px-4 py-2.5 flex items-baseline gap-3 flex-wrap">
      <span className="font-mono text-[11.5px] text-subtle min-w-0 truncate max-w-[220px]">
        {example.doc_ref ?? example.doc_key.slice(0, 16)}
      </span>
      <span
        className="text-[11px]"
        style={{ color: SOURCE_TONE[example.label_source] ?? "var(--muted)" }}
        title={
          example.label_source === "judge"
            ? "Proposed by a model. Scores against judge labels partly measure agreement, not correctness."
            : undefined
        }
      >
        {example.label_source}
      </span>
      {example.split === "holdout" && (
        <span
          className="text-[11px] text-subtle"
          title="Excluded from the headline score and reported separately."
        >
          holdout
        </span>
      )}
      <span className="flex items-baseline gap-3 ml-auto flex-wrap justify-end">
        {fields.map((f) => (
          <span key={f} className="text-[12px]">
            <span className="text-subtle text-[11px]">{f} </span>
            <span className="font-mono">{String(example.labels[f] ?? "—")}</span>
          </span>
        ))}
      </span>
    </div>
  );
}

function ImportBox({ evalSetId, onDone }: { evalSetId: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const run = async () => {
    setBusy(true);
    try {
      const res = await importEvalExamples(evalSetId, { format: "csv", content });
      if (res.errors.length) {
        // Partial success is reported as such. Reporting only the count
        // imported would hide rows that silently never landed.
        toast.error({
          title: `Imported ${res.imported}, skipped ${res.errors.length}`,
          message: "Some rows didn't have a valid doc_key.",
          detail: res.errors.map((e) => `row ${e.row}: ${e.error}`).join("\n"),
        });
      } else {
        toast.success({
          title: `Imported ${res.imported} labels`,
          message: `Labels are now at v${res.labels_version}.`,
        });
      }
      setContent("");
      setOpen(false);
      onDone();
    } catch (e) {
      toast.error(humanizeError(e, { action: "import", entity: "labels" }));
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <div>
        <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>
          Import labels (CSV)
        </Button>
      </div>
    );
  }

  return (
    <Panel>
      <PanelHead label="Import labels" />
      <div className="px-4 py-3 flex flex-col gap-2">
        <p className="text-[12.5px] text-muted">
          CSV with a <code className="font-mono">doc_key</code> column (the
          document&apos;s sha256) plus one column per field. Keying on content
          rather than filename means labels survive renames and moves.
        </p>
        <Textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={6}
          placeholder={"doc_key,invoice_no,total\n<sha256>,INV-1001,1240.50"}
        />
        <div className="flex items-center gap-2">
          <Button variant="primary" size="sm" disabled={busy || !content.trim()} onClick={() => void run()}>
            {busy ? "Importing…" : "Import"}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </div>
      </div>
    </Panel>
  );
}
