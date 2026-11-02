import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import {
  Button,
  ErrorPanel,
  JsonCell,
  Panel,
  PanelHead,
  SectionHead,
  Segmented,
} from "@/components/ui";
import {
  dropSourceSample,
  dryRunPipeline,
  estimatePipeline,
  getPipeline,
  previewPipeline,
  type Pipeline,
  type PipelineParam,
  type PreviewResponse,
} from "@/lib/api";
import { sampleAge, useReadsMetered } from "@/lib/metered";
import type { PipelineEstimate } from "@/lib/api";
import { humanizeCompilerError, humanizeError } from "@/lib/errors";
import { ParamsModal } from "@/components/params-modal";
import { InspectRowButton } from "@/components/document-inspector/InspectRowButton";
import { visibleColumns } from "@/lib/system-columns";

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
 *
 * Plan-039 adds a Data | SQL toggle so the user can inspect the compiled
 * per-step SQL and final SELECT alongside the sample rows.
 */
export function PipelinePreview({ pipelineId }: { pipelineId: string | Pipeline }) {
  const [rawData, setData] = useState<PreviewResponse | null>(null);
  const [rawErr, setErr] = useState<unknown>(null);
  const [rawBusy, setBusy] = useState(false);
  const [view, setView] = useState<"data" | "sql">("data");
  // Bumped by Refresh so live mode refetches after the samples are dropped.
  const [refreshSeq, setRefreshSeq] = useState(0);
  // Whether the rows on screen came from the warehouse rather than a sample.
  const [shownLive, setShownLive] = useState(false);

  const isLive = typeof pipelineId !== "string";
  // Serialise the pipeline for a stable useEffect dep. Fires on any content
  // change; JSON.stringify is fine here — the object is small.
  const liveKey = isLive ? JSON.stringify(pipelineId) : "";

  // Track the last request so a stale response can't overwrite a fresh one.
  const reqSeq = useRef(0);

  // Live mode carries params on the pipeline object; saved mode fetches the
  // pipeline once to read the declared params list.
  const { data: savedPipeline } = useSWR<Pipeline>(!isLive ? ["pipeline", pipelineId] : null, () =>
    getPipeline(pipelineId as string),
  );
  const declaredParams: PipelineParam[] = useMemo(() => {
    if (isLive) return (pipelineId as Pipeline).params ?? [];
    return savedPipeline?.params ?? [];
  }, [isLive, pipelineId, savedPipeline]);

  // Values collected via the ParamsModal — persisted across re-runs so the
  // user isn't reprompted on every keystroke in live mode.
  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [modalOpen, setModalOpen] = useState(false);
  // Whether we still need to prompt before running: any required declared
  // input with no default and no value.
  const needsPrompt = declaredParams.some((p) => {
    const requiredNoDefault = p.required !== false && (p.default ?? "") === "";
    return requiredNoDefault && !paramValues[p.name];
  });

  // A live pipeline without enough shape to compile shows nothing (no 422
  // flood), and a pending prompt means no request is in flight. Derived at
  // render so the effect never has to reset state.
  const livePipeline = isLive ? (pipelineId as Pipeline) : null;
  const liveNotReady =
    !!livePipeline &&
    (!livePipeline.sources || livePipeline.sources.length === 0 || !livePipeline.output_id);
  const data = liveNotReady ? null : rawData;
  const err = liveNotReady ? null : rawErr;
  const busy = isLive && (liveNotReady || needsPrompt) ? false : rawBusy;
  // Plan 093: a warehouse bills every query, so its preview waits for a click
  // instead of firing on each edit. Unknown (lists loading) counts as metered.
  const metered = useReadsMetered(livePipeline?.sources) !== false;
  // Bumped by the Preview button; the effect runs once per click when metered.
  const [previewSeq, setPreviewSeq] = useState(0);
  // A priced live preview awaiting the user's go-ahead.
  const [liveEstimate, setLiveEstimate] = useState<PipelineEstimate | null>(null);

  const runSaved = async (overrideValues?: Record<string, string>) => {
    if (isLive) return;
    if (needsPrompt && !overrideValues) {
      setModalOpen(true);
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await previewPipeline(pipelineId as string, 20, overrideValues ?? paramValues);
      setData(res);
      setShownLive(false);
    } catch (e) {
      setErr(e);
      setData(null);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!isLive) return;
    const pipeline = pipelineId as Pipeline;
    // Not ready / awaiting inputs: nothing to fetch (see derived state above).
    if (liveNotReady || needsPrompt) return;
    if (metered && previewSeq === 0) return;
    const seq = ++reqSeq.current;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- loading flag for the async request this effect starts
    setBusy(true);
    const t = window.setTimeout(async () => {
      try {
        const res = await dryRunPipeline(pipeline, 20, paramValues);
        if (reqSeq.current !== seq) return; // superseded
        setData(res);
        setShownLive(false);
        setErr(null);
      } catch (e) {
        if (reqSeq.current !== seq) return;
        setErr(e);
        setData(null);
      } finally {
        if (reqSeq.current === seq) setBusy(false);
      }
    }, metered ? 0 : 500);
    return () => window.clearTimeout(t);
    // `liveKey` stands in for the pipeline; when metered, edits must not
    // refetch, so the pipeline only reaches the effect through a click.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLive, metered ? previewSeq : liveKey, needsPrompt, paramValues, liveNotReady, refreshSeq, metered]);

  // System columns ride on every extracted row and cannot be projected
  // away, so this is where they are kept out of sight. The rows still carry
  // them, which is what lets Inspect work on a table that never shows them.
  const columns = visibleColumns(data?.rows?.[0] ? Object.keys(data.rows[0]) : []);
  // Backend now returns 200 with `error` populated on compile failure so
  // partial SQL can accompany the failure. Surface both fetch-level errors
  // (network / HTTP) and payload-level compile errors.
  const compileErr = data?.error ?? null;
  const humanized =
    err != null
      ? humanizeError(err, { action: "run preview", entity: "pipeline" })
      : humanizeCompilerError(compileErr);
  const displayErr = humanized;
  const pipelineObj = isLive ? (pipelineId as Pipeline) : (savedPipeline ?? null);
  const samples = data?.samples ?? [];

  // Plan 093: warehouse sources preview from a cached sample. Refresh drops
  // the samples and re-runs; the next preview fetches new ones.
  const refreshSamples = async () => {
    try {
      await Promise.all(samples.map((s) => dropSourceSample(s.source_id, s.table)));
    } catch (e) {
      setErr(e);
      return;
    }
    if (isLive) setRefreshSeq((n) => n + 1);
    else await runSaved();
  };

  // A live preview is a billed query. A small one just runs; a big one says
  // what it costs inline and runs on the user's go-ahead. The next edit goes
  // back to the sample.
  const priceLive = async () => {
    if (!pipelineObj) return;
    setBusy(true);
    setErr(null);
    let est: PipelineEstimate;
    try {
      est = await estimatePipeline(pipelineObj, paramValues);
    } catch (e) {
      setErr(e);
      setBusy(false);
      return;
    }
    if (est.needs_confirm) {
      setLiveEstimate(est);
      setBusy(false);
    } else {
      await previewLive();
    }
  };

  const previewLive = async () => {
    if (!pipelineObj) return;
    setLiveEstimate(null);
    setBusy(true);
    setErr(null);
    try {
      const res = isLive
        ? await dryRunPipeline(pipelineObj, 20, paramValues, true)
        : await previewPipeline(pipelineId as string, 20, paramValues, true);
      reqSeq.current++; // a debounced sample preview must not overwrite this
      setData(res);
      setShownLive(true);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <SectionHead
        title={isLive ? "Live preview" : "Dry run"}
        count={
          data
            ? `· ${data.count} row${data.count === 1 ? "" : "s"} (limit 20)`
            : isLive
              ? metered
                ? "· on demand: warehouse queries are billed"
                : "· updates as you edit"
              : "· compile + sample without writing output"
        }
        actions={
          <div className="flex items-center gap-2">
            <Segmented
              value={view}
              onChange={setView}
              options={[
                { value: "data", label: "Data" },
                { value: "sql", label: "SQL" },
              ]}
            />
            {declaredParams.length > 0 && (
              <Button variant="ghost" size="sm" onClick={() => setModalOpen(true)}>
                Inputs · {Object.keys(paramValues).length}/{declaredParams.length}
              </Button>
            )}
            {isLive && metered && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => setPreviewSeq((n) => n + 1)}
                disabled={busy || liveNotReady || needsPrompt}
              >
                {busy ? "Running…" : data ? "Re-run" : "Preview"}
              </Button>
            )}
            {isLive ? null : (
              <Button variant="primary" size="sm" onClick={() => runSaved()} disabled={busy}>
                {busy ? "Running…" : data ? "Re-run" : "Dry run"}
              </Button>
            )}
          </div>
        }
      />

      <ParamsModal
        title={isLive ? "Preview inputs" : "Dry-run inputs"}
        submitLabel={isLive ? "Preview" : "Dry run"}
        params={declaredParams}
        initialValues={paramValues}
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        emptyMessage="This pipeline has no declared inputs."
        onSubmit={async (values) => {
          setParamValues(values);
          setModalOpen(false);
          if (!isLive) await runSaved(values);
          // Live mode auto-re-runs via the useEffect dep on paramValues.
        }}
      />

      {(samples.length > 0 || shownLive) && (
        <div className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-subtle">
          {shownLive ? (
            <span>Preview on live data · the next edit or re-run goes back to the sample</span>
          ) : (
            <>
              <span>
                Preview on {Math.max(...samples.map((s) => s.rows)).toLocaleString()}-row sample ·
                taken {sampleAge(samples.map((s) => s.taken_at).sort()[0]!)}
              </span>
              <Button variant="ghost" size="sm" onClick={refreshSamples} disabled={busy}>
                Refresh
              </Button>
              {liveEstimate ? (
                <>
                  <span className="text-text">
                    {liveEstimate.message}
                  </span>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={previewLive}
                    disabled={busy || liveEstimate.exceeds_cap}
                  >
                    Run live preview
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setLiveEstimate(null)}>
                    Cancel
                  </Button>
                </>
              ) : (
                <Button variant="ghost" size="sm" onClick={priceLive} disabled={busy}>
                  Preview on live data
                </Button>
              )}
            </>
          )}
        </div>
      )}

      {isLive && needsPrompt && !modalOpen && (
        <div className="p-4 border border-dashed border-border rounded bg-code-bg text-subtle text-[12.5px] flex items-center justify-between">
          <span>
            Waiting on{" "}
            {
              declaredParams.filter(
                (p) => p.required !== false && (p.default ?? "") === "" && !paramValues[p.name],
              ).length
            }{" "}
            required input(s) to run preview.
          </span>
          <Button variant="primary" size="sm" onClick={() => setModalOpen(true)}>
            Enter inputs
          </Button>
        </div>
      )}

      {isLive && busy && !data && !displayErr && (
        <div className="p-6 text-center text-subtle text-sm">Compiling…</div>
      )}

      {isLive && !busy && !data && !displayErr && (
        <div className="p-6 text-center text-subtle text-sm">
          {liveNotReady
            ? "Pick at least one source and a destination to preview."
            : metered
              ? "This pipeline reads a billed warehouse. Click Preview to run it on a sample."
              : null}
        </div>
      )}

      {displayErr && (
        <ErrorPanel
          title={displayErr.title}
          message={displayErr.message}
          detail={displayErr.detail}
        />
      )}

      {view === "data" && data && !err && (
        <Panel>
          <PanelHead label="Sample rows" count={data.count} />
          {columns.length === 0 || data.rows.length === 0 ? (
            <div className="p-6 text-center text-subtle text-sm">
              {compileErr
                ? "No rows — compile failed before execute."
                : "Compile succeeded but produced zero rows."}
            </div>
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

      {view === "sql" && (!data || !!err) && !displayErr && (
        <div className="p-6 text-center text-subtle text-sm">
          SQL will appear once the pipeline compiles.
        </div>
      )}

      {view === "sql" && data && <SqlPanel data={data} pipeline={pipelineObj} />}
    </section>
  );
}

/**
 * SqlPanel — plan-039.
 *
 * Renders per-step compiled SQL and the LIMIT-wrapped final SELECT with a
 * Copy button on each block. Step labels use the op from the pipeline object
 * when available (live mode); otherwise they show a generic "Step N" heading.
 */
function SqlPanel({ data, pipeline }: { data: PreviewResponse; pipeline: Pipeline | null }) {
  const isQualityPipeline = pipeline?.pipeline_type === "quality";
  const stepSqls = data.step_sqls ?? {};
  // Transform pipelines capture one SQL block per step (each op is compiled
  // individually) — showing all of them is noise once the final compiled
  // query is available. Quality pipelines have no final_sql; one block per
  // check is the actual content, so keep the per-step breakdown there.
  const stepEntries: Array<[number, string]> = isQualityPipeline
    ? Object.entries(stepSqls)
        .map(([k, v]) => [Number(k), v] as [number, string])
        .sort((a, b) => a[0] - b[0])
    : [];
  const finalSql = data.final_sql ?? null;

  if (stepEntries.length === 0 && !finalSql) {
    return (
      <div className="p-6 text-center text-subtle text-sm">
        SQL will appear once the pipeline compiles.
      </div>
    );
  }

  const stepOp = (idx: number): string => {
    const s = pipeline?.steps?.[idx] as { op?: string } | undefined;
    return s?.op ?? "step";
  };

  return (
    <div className="flex flex-col gap-3">
      {stepEntries.map(([idx, sql]) => (
        <SqlBlock key={`step-${idx}`} label={`Step ${idx + 1} · ${stepOp(idx)}`} sql={sql} />
      ))}
      {finalSql && <SqlBlock label="Final query" sql={finalSql} />}
    </div>
  );
}

function SqlBlock({ label, sql }: { label: string; sql: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      // Clipboard permission denied — swallow; user can still select+copy.
    }
  };
  return (
    <Panel>
      <PanelHead
        label={label}
        count={
          <Button variant="ghost" size="sm" onClick={copy}>
            {copied ? "Copied" : "Copy"}
          </Button>
        }
      />
      <pre className="font-mono text-[11px] bg-code-bg p-3 rounded-sm whitespace-pre-wrap overflow-x-auto">
        {sql}
      </pre>
    </Panel>
  );
}
