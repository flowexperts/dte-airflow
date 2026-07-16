"use client";

import { useState } from "react";
import { Button, JsonCell, Panel, PanelHead, SectionHead } from "@/components/ui";
import { getRunOutput, type PreviewResponse } from "@/lib/api";

const SUPPORTED = new Set(["json_file", "csv_file", "excel_file"]);

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
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const supported = outputType ? SUPPORTED.has(outputType) : false;

  const load = async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await getRunOutput(runId, 5);
      setData(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setData(null);
    } finally {
      setBusy(false);
    }
  };

  const columns = data?.rows?.[0] ? Object.keys(data.rows[0]) : [];

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
            <Button
              variant="primary"
              size="sm"
              onClick={load}
              disabled={busy || disabled}
            >
              {busy ? "Loading…" : data ? "Reload" : "Load preview"}
            </Button>
          ) : null
        }
      />

      {!supported && (
        <Panel>
          <div className="p-6 text-center text-subtle text-sm">
            Preview not supported for {outputType ?? "unknown"} outputs yet.
          </div>
        </Panel>
      )}

      {supported && err && (
        <Panel>
          <PanelHead label="Error" />
          <pre className="p-4 font-mono text-[12px] text-red whitespace-pre-wrap break-words">
            {err}
          </pre>
        </Panel>
      )}

      {supported && data && !err && (
        <Panel>
          <PanelHead label="Rows" count={data.count} />
          {columns.length === 0 || data.rows.length === 0 ? (
            <div className="p-6 text-center text-subtle text-sm">
              Output file is empty.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr className="border-b border-border bg-surface-2">
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
                    <tr
                      key={i}
                      className="border-b border-border last:border-b-0 hover:bg-hover"
                    >
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
