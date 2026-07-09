"use client";

import { useState } from "react";
import {
  Button,
  Panel,
  PanelHead,
  SectionHead,
} from "@/components/ui";
import { previewPipeline, type PreviewResponse } from "@/lib/api";

export function PipelinePreview({ pipelineId }: { pipelineId: string }) {
  const [data, setData] = useState<PreviewResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      const res = await previewPipeline(pipelineId, 20);
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
        title="Dry run"
        count={
          data
            ? `· ${data.count} row${data.count === 1 ? "" : "s"} (limit 20)`
            : "· compile + sample without writing output"
        }
        actions={
          <Button
            variant="primary"
            size="sm"
            onClick={run}
            disabled={busy}
          >
            {busy ? "Running…" : data ? "Re-run" : "Dry run"}
          </Button>
        }
      />

      {err && (
        <Panel>
          <PanelHead label="Error" />
          <pre className="p-4 font-mono text-[12px] text-red whitespace-pre-wrap break-words">
            {err}
          </pre>
        </Panel>
      )}

      {data && !err && (
        <Panel>
          <PanelHead label="Sample rows" count={data.count} />
          {columns.length === 0 || data.rows.length === 0 ? (
            <div className="p-6 text-center text-subtle text-sm">
              Compile succeeded but produced zero rows.
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
                          className="px-3 py-2 font-mono text-[12px] text-text tabular-nums truncate max-w-[280px]"
                          title={String(row[c] ?? "")}
                        >
                          {row[c] === null || row[c] === undefined ? (
                            <span className="text-subtle">null</span>
                          ) : (
                            String(row[c])
                          )}
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
