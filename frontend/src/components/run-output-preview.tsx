import { useState } from "react";
import { Button, ErrorPanel, JsonCell, Panel, PanelHead, SectionHead } from "@/components/ui";
import { getRunOutput, type PreviewResponse } from "@/lib/api";
import { InspectRowButton } from "@/components/document-inspector/InspectRowButton";
import { visibleColumns } from "@/lib/system-columns";
import { humanizeError, type HumanError } from "@/lib/errors";

const SUPPORTED = new Set(["json", "csv", "excel"]);

export function RunOutputPreview({
  runId,
  outputType,
  disabled,
}: {
  runId: string;
  outputType: string | undefined;
  disabled: boolean;
}) {
  const [data, setData] = useState<PreviewResponse | null>(null);
  const [err, setErr] = useState<HumanError | null>(null);
  const [busy, setBusy] = useState(false);

  const supported = outputType ? SUPPORTED.has(outputType) : false;

  const load = async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await getRunOutput(runId, 5);
      setData(res);
    } catch (e) {
      setErr(humanizeError(e, { action: "load", entity: "output" }));
      setData(null);
    } finally {
      setBusy(false);
    }
  };

  // System columns ride on every extracted row and cannot be projected
  // away, so this is where they are kept out of sight. The rows still carry
  // them, which is what lets Inspect work on a table that never shows them.
  const columns = visibleColumns(data?.rows?.[0] ? Object.keys(data.rows[0]) : []);

  // Nothing to show and no way to show it — collapse the whole section to one
  // line rather than heading an empty full-width panel.
  if (!supported) {
    return (
      <div className="flex items-center justify-between gap-4 px-4 py-2.5 rounded-[var(--radius)] bg-surface-2 border border-dashed border-border-2 text-[12.5px] text-subtle">
        <span>Output preview — not supported for {outputType ?? "unknown"} outputs yet</span>
        <span className="font-mono text-[11px]">{outputType ?? "unknown"}</span>
      </div>
    );
  }

  return (
    <section>
      <SectionHead
        title="Output preview"
        count={
          data
            ? `· first ${data.count} row${data.count === 1 ? "" : "s"}`
            : "· read the output on demand"
        }
        actions={
          supported ? (
            <Button variant="primary" size="sm" onClick={load} disabled={busy || disabled}>
              {busy ? "Loading…" : data ? "Reload" : "Load preview"}
            </Button>
          ) : null
        }
      />

      {supported && err && (
        <ErrorPanel title={err.title} message={err.message} detail={err.detail} />
      )}

      {supported && data && !err && (
        <Panel>
          <PanelHead label="Rows" count={data.count} />
          {columns.length === 0 || data.rows.length === 0 ? (
            <div className="p-6 text-center text-subtle text-sm">Output file is empty.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr className="border-b border-border bg-surface-2">
                    <th className="w-8 px-3 py-2" />
                    {columns.map((c) => (
                      <th
                        key={c}
                        className="text-left px-3 py-2 font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle"
                      >
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row, i) => (
                    <tr key={i} className="border-b border-border last:border-b-0 hover:bg-hover">
                      {/* Renders nothing unless the row is backed by a
                          document, so non-document pipelines see an empty
                          8px gutter rather than a dead column. */}
                      <td className="w-8 px-3 py-2 align-top">
                        <InspectRowButton row={row as Record<string, unknown>} />
                      </td>
                      {columns.map((c) => (
                        <td
                          key={c}
                          className="px-3 py-2 font-mono text-[12px] text-text tabular-nums align-top"
                        >
                          <JsonCell value={row[c]} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      )}
    </section>
  );
}
