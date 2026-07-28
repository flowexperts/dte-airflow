"use client";

import { useEffect, useRef, useState } from "react";
import {
  Button,
  JsonCell,
  Panel,
  PanelHead,
  SectionHead,
} from "@/components/ui";
import {
  dryRunPipeline,
  previewPipeline,
  type Pipeline,
  type PreviewResponse,
} from "@/lib/api";

/**
 * PipelinePreview
 *
 * Two modes:
 *  - **saved pipeline (string id)** — hit `GET /api/pipelines/{id}/preview`
 *    on the user's click. Same behaviour as before this component was
 *    generalised.
 *  - **unsaved pipeline (Pipeline object)** — debounce ~500ms whenever the
 *    spec changes and POST it to `/api/pipelines/dry-run`. Powers the
 *    builder split-pane live preview (plan 038 item 6).
 *
 * The two flavours share the same rendering path — only the fetch call and
 * the trigger (click vs. debounce) differ.
 */
export function PipelinePreview({
  pipelineId,
}: {
  pipelineId: string | Pipeline;
}) {
  const [data, setData] = useState<PreviewResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isLive = typeof pipelineId !== "string";
  // Serialise the pipeline for a stable useEffect dep. Fires on any content
  // change; JSON.stringify is fine here — the object is small.
  const liveKey = isLive ? JSON.stringify(pipelineId) : "";

  // Track the last request so a stale response can't overwrite a fresh one.
  const reqSeq = useRef(0);

  const runSaved = async () => {
    if (isLive) return;
    setBusy(true);
    setErr(null);
    try {
      const res = await previewPipeline(pipelineId as string, 20);
      setData(res);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setData(null);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!isLive) return;
    const pipeline = pipelineId as Pipeline;
    // Skip until the pipeline has enough shape to compile — otherwise every
    // keystroke on an empty form generates a 422 flood.
    if (
      !pipeline.sources ||
      pipeline.sources.length === 0 ||
      !pipeline.output_id
    ) {
      setData(null);
      setErr(null);
      setBusy(false);
      return;
    }
    const seq = ++reqSeq.current;
    setBusy(true);
    const t = window.setTimeout(async () => {
      try {
        const res = await dryRunPipeline(pipeline, 20);
        if (reqSeq.current !== seq) return; // superseded
        setData(res);
        setErr(null);
      } catch (e) {
        if (reqSeq.current !== seq) return;
        setErr(e instanceof Error ? e.message : String(e));
        setData(null);
      } finally {
        if (reqSeq.current === seq) setBusy(false);
      }
    }, 500);
    return () => window.clearTimeout(t);
  }, [isLive, liveKey, pipelineId]);

  const columns = data?.rows?.[0] ? Object.keys(data.rows[0]) : [];

  return (
    <section>
      <SectionHead
        title={isLive ? "Live preview" : "Dry run"}
        count={
          data
            ? `· ${data.count} row${data.count === 1 ? "" : "s"} (limit 20)`
            : isLive
              ? "· updates as you edit"
              : "· compile + sample without writing output"
        }
        actions={
          isLive ? undefined : (
            <Button
              variant="primary"
              size="sm"
              onClick={runSaved}
              disabled={busy}
            >
              {busy ? "Running…" : data ? "Re-run" : "Dry run"}
            </Button>
          )
        }
      />

      {isLive && busy && !data && !err && (
        <div className="p-6 text-center text-subtle text-sm">Compiling…</div>
      )}

      {isLive && !busy && !data && !err && (
        <div className="p-6 text-center text-subtle text-sm">
          Pick at least one source and a destination to preview.
        </div>
      )}

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
