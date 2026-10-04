import { useSearchParams } from "@/lib/nav";
import { MissingParam } from "@/components/missing-param";
import { withSuspense } from "@/components/with-suspense";
import useSWR from "swr";
import { Link } from "@/lib/nav";
import {
  Button,
  ErrorPanel,
  InlineCode,
  KV,
  KVItem,
  Metric,
  MetricRow,
  PageHeader,
  Panel,
  PanelHead,
  Pill,
  Topbar,
} from "@/components/ui";
import {
  getDestination,
  getPipeline,
  getRun,
  getRunEvents,
  getRunQuality,
  isTerminal,
  type Destination,
  type Pipeline,
  type QualityCheckResult,
  type Run,
  type RunEvent,
} from "@/lib/api";
import { RunOutputPreview } from "@/components/run-output-preview";
import { Diagnostics } from "@/components/run/diagnostics";
import { QualityPanel, QualityStrip } from "@/components/run/quality-panel";
import { FailedSteps, FixStepLink } from "@/components/run/failed-steps";
import { StatRail, StatRow } from "@/components/run/stat-rail";
import { VerdictBanner } from "@/components/run/verdict-banner";
import {
  STATUS_LABEL,
  elapsedMs,
  elapsedSeconds,
  qualityTally,
  statusTone,
  type Tone,
} from "@/components/run/helpers";
import { humanizeCompilerError } from "@/lib/errors";
import type { StepShape } from "@/components/builder/steps/types";

/** Quality results carry the label their `check` step declared, which is the
 *  only handle we have to point back at it. Unlabelled checks get no link
 *  rather than a wrong one. */
function checkStepIndex(
  pipeline: Pipeline | undefined,
  label: string | null | undefined,
): number {
  if (!pipeline || !label) return -1;
  const steps = (pipeline.steps ?? []) as StepShape[];
  return steps.findIndex(
    (s) => (s.op === "check" || s.op === "profile") && s.label === label,
  );
}

function RevisionLink({ run }: { run: Run }) {
  if (!run.revision_id || !run.pipeline_id) return null;
  return (
    <>
      Compiled from revision{" "}
      {/* The revision, not the pipeline. Pointing at the live pipeline showed
          whatever it looks like now — which is exactly the spec that did NOT
          produce this run once anyone has edited since. */}
      <Link
        href={`/pipelines/revision?id=${encodeURIComponent(run.pipeline_id)}&rev=${encodeURIComponent(run.revision_id)}`}
        className="text-accent hover:underline"
        title="Open the pipeline as it stood for this run (read-only)"
      >
        {run.revision_id.slice(0, 8)}
      </Link>
    </>
  );
}

function TriggerParams({ run }: { run: Run }) {
  const params = run.params?.params;
  if (!params || Object.keys(params).length === 0) return null;
  return (
    <Panel>
      <PanelHead label="Trigger params" count={Object.keys(params).length} />
      <KV>
        {Object.entries(params).map(([k, v]) => (
          <KVItem key={k} label={k} value={<InlineCode>{v}</InlineCode>} />
        ))}
      </KV>
    </Panel>
  );
}

function RunErrorPanel({ run }: { run: Run }) {
  if (!run.error) return null;
  const title = run.status === "failed_quality" ? "Quality checks failed" : undefined;
  const h = humanizeCompilerError(run.error);
  return h ? (
    <ErrorPanel title={title ?? h.title} message={h.message} detail={h.detail} />
  ) : (
    <ErrorPanel title={title ?? "Run failed"} message={run.error} detail={null} />
  );
}

/* ------------------------------------------------------------------ *
 * Quality run — the checks ARE the run. Verdict first, checks primary,
 * numbers demoted to a rail. No rows-written tile and no output preview:
 * a quality pipeline writes nothing, and a "0 rows" hero reads as failure.
 * ------------------------------------------------------------------ */
function QualityRunBody({
  run,
  results,
  events,
  pipeline,
}: {
  run: Run;
  results: QualityCheckResult[];
  events: RunEvent[];
  pipeline: Pipeline | undefined;
}) {
  const tally = qualityTally(results, run.quality);
  const bad = tally.failed + tally.warned;
  const firstProblem = results.find((r) => !r.passed);
  const tone = statusTone(run.status);
  const bannerTone: Tone = tone === "pending" ? "warn" : tone;

  const stepSqls = new Map<number, string>(
    Object.entries(run.sql_query?.step_sqls ?? {}).map(([k, v]) => [Number(k), v]),
  );

  return (
    <>
      {run.error ? (
        <RunErrorPanel run={run} />
      ) : (
        isTerminal(run.status) && (
          <VerdictBanner
            tone={bannerTone}
            headline={
              bad > 0 ? (
                <>
                  {bad} of {tally.total} quality check
                  {tally.total === 1 ? "" : "s"} failed on this run
                  {firstProblem && (
                    <> — “{firstProblem.label ?? firstProblem.contract_type}”</>
                  )}
                </>
              ) : (
                <>
                  All {tally.total} quality check{tally.total === 1 ? "" : "s"} passed
                </>
              )
            }
            sub={firstProblem?.detail ?? undefined}
            meta={<RevisionLink run={run} />}
          />
        )
      )}

      <FailedSteps events={events} pipeline={pipeline} />

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_268px] xl:grid-cols-[1fr_320px] gap-5 items-start">
        {results.length > 0 ? (
          <QualityPanel
            results={results}
            totalRows={null}
            failedCount={bad}
            actionFor={(r) => {
              const idx = checkStepIndex(pipeline, r.label);
              return !r.passed && idx >= 0 && pipeline ? (
                <FixStepLink
                  pipelineId={pipeline.id}
                  index={idx}
                  label="Edit check"
                />
              ) : null;
            }}
          />
        ) : (
          <Panel>
            <PanelHead label="Quality checks" />
            <div className="px-4 py-8 text-center text-subtle text-sm">
              {isTerminal(run.status)
                ? "No check results recorded for this run."
                : "Evaluating…"}
            </div>
          </Panel>
        )}

        <StatRail>
          <StatRow
            label="Checks passed"
            value={`${tally.passed} / ${tally.total}`}
            tone={bad > 0 ? "warn" : "ok"}
          />
          <StatRow
            label="Elapsed"
            value={elapsedSeconds(run.started_at, run.finished_at)}
          />
          <StatRow
            label="Started"
            value={run.started_at ? new Date(run.started_at).toLocaleString() : "—"}
            small
          />
          <StatRow label="Engine" value="DuckDB" small />
        </StatRail>
      </div>

      <TriggerParams run={run} />

      <Diagnostics
        events={events}
        stepSqls={stepSqls}
        finalSql={run.sql_query?.final_sql ?? null}
        sqlTabLabel="Check SQL"
      />
    </>
  );
}

/* ------------------------------------------------------------------ *
 * Transform run — the OUTPUT is the run. Throughput metrics lead, the
 * written data is the primary panel, and quality checks (if any) are a
 * collapsed assertion strip rather than the headline.
 * ------------------------------------------------------------------ */
function TransformRunBody({
  run,
  runId,
  results,
  events,
  destination,
  pipeline,
}: {
  run: Run;
  runId: string;
  results: QualityCheckResult[];
  events: RunEvent[];
  destination: Destination | undefined;
  pipeline: Pipeline | undefined;
}) {
  const tally = qualityTally(results, run.quality);
  const bad = tally.failed + tally.warned;
  const tone = statusTone(run.status);
  const ms = elapsedMs(run.started_at, run.finished_at);
  const rows = run.rows_written ?? null;
  const throughput =
    rows !== null && ms !== null && ms > 0
      ? Math.round(rows / (ms / 1000)).toLocaleString()
      : "—";

  return (
    <>
      {run.error ? (
        <RunErrorPanel run={run} />
      ) : (
        isTerminal(run.status) && (
          <VerdictBanner
            tone={tone === "pending" ? "warn" : tone}
            headline={
              <>
                Wrote {rows?.toLocaleString() ?? "—"} row{rows === 1 ? "" : "s"}
                {destination?.config?.type && (
                  <> to {destination.config.type.replace(/_/g, " ")}</>
                )}
                {bad > 0 && (
                  <>
                    {" "}
                    with {bad} quality warning{bad === 1 ? "" : "s"}
                  </>
                )}
              </>
            }
            sub={`Finished in ${elapsedSeconds(run.started_at, run.finished_at)}.`}
            meta={<RevisionLink run={run} />}
          />
        )
      )}

      <FailedSteps events={events} pipeline={pipeline} />

      <MetricRow className="lg:grid-cols-4">
        <Metric
          label="Rows written"
          value={rows?.toLocaleString() ?? "—"}
          tone={tone === "ok" || tone === "warn" ? "ok" : "default"}
        />
        <Metric
          label="Elapsed"
          value={elapsedSeconds(run.started_at, run.finished_at)}
        />
        <Metric label="Throughput" value={throughput} unit="rows/s" />
        <Metric
          label="Started"
          value={
            run.started_at ? (
              <span className="text-[18px]">
                {new Date(run.started_at).toLocaleString()}
              </span>
            ) : (
              "—"
            )
          }
        />
      </MetricRow>

      <RunOutputPreview
        runId={runId}
        outputType={destination?.config?.type}
        disabled={run.status !== "completed"}
      />

      {results.length > 0 && (
        <QualityStrip
          results={results}
          totalRows={rows}
          failedCount={bad}
          actionFor={(r) => {
            const idx = checkStepIndex(pipeline, r.label);
            return !r.passed && idx >= 0 && pipeline ? (
              <FixStepLink
                pipelineId={pipeline.id}
                index={idx}
                label="Edit check"
              />
            ) : null;
          }}
        />
      )}

      <TriggerParams run={run} />

      {/* Transform runs capture one SQL block per step, which is noise next to
          the single final compiled query — show the final query only. */}
      <Diagnostics
        events={events}
        stepSqls={new Map()}
        finalSql={run.sql_query?.final_sql ?? null}
        sqlTabLabel="Compiled SQL"
      />
    </>
  );
}

function RunDetail() {
  const id = useSearchParams().get("id") ?? "";

  const { data, error, isLoading } = useSWR<Run>(id ? ["run", id] : null, () => getRun(id), {
    refreshInterval: (latest) => (isTerminal(latest?.status) ? 0 : 2000),
  });

  const { data: pipeline } = useSWR<Pipeline>(
    data?.pipeline_id ? ["pipeline", data.pipeline_id] : null,
    () => getPipeline(data!.pipeline_id),
  );
  const { data: destination } = useSWR<Destination>(
    pipeline?.output_id ? ["destination", pipeline.output_id] : null,
    () => getDestination(pipeline!.output_id),
  );
  const { data: eventsResp } = useSWR<{ events: RunEvent[]; count: number }>(
    id ? ["run-events", id] : null,
    () => getRunEvents(id),
    { refreshInterval: (l) => (isTerminal(data?.status) && l?.count ? 0 : 2000) },
  );
  const events = eventsResp?.events ?? [];

  const { data: qualityResp } = useSWR<{
    results: QualityCheckResult[];
    count: number;
  }>(isTerminal(data?.status) ? ["run-quality", id] : null, () => getRunQuality(id));
  const results = qualityResp?.results ?? [];

  const isQuality = pipeline?.pipeline_type === "quality";
  const tone = statusTone(data?.status);
  const pillStatus =
    tone === "ok"
      ? "ok"
      : tone === "warn"
        ? "warn"
        : tone === "err"
          ? "failed"
          : data?.status === "running"
            ? "running"
            : "pending";

  return (
    <>
      <Topbar
        /* "Runs" was a dead label under a Workspace root, so the trail
           described nowhere you could go back to — and skipped the pipeline
           entirely, which is the only thing a run belongs to. Now it walks
           the real containment: workspace → pipelines → this pipeline →
           its Runs tab → this run. */
        crumbs={[
          { label: "DTE Pipelines", href: "/pipelines" },
          ...(data?.pipeline_id
            ? [
                {
                  label: pipeline?.name ?? data.pipeline_id,
                  href: `/pipelines/detail?id=${encodeURIComponent(data.pipeline_id)}`,
                },
                {
                  label: "Runs",
                  href: `/pipelines/detail?id=${encodeURIComponent(data.pipeline_id)}&tab=runs`,
                },
              ]
            : [{ label: "Runs" }]),
          { label: id.slice(0, 8) },
        ]}
        actions={
          data?.pipeline_id ? (
            <Link href={`/pipelines/detail?id=${encodeURIComponent(data.pipeline_id)}`}>
              <Button size="sm">Back to pipeline</Button>
            </Link>
          ) : null
        }
      />
      <PageHeader
        title={
          <>
            Run{" "}
            <span className="font-mono text-[18px] text-subtle">{id.slice(0, 8)}</span>
          </>
        }
        sub={isQuality ? "quality" : "transform"}
        lede={data?.pipeline_id}
        actions={data ? <Pill status={pillStatus}>{STATUS_LABEL[data.status]}</Pill> : null}
      />

      <div className="px-14 py-8">
        <div className="space-y-5">
          {error ? (
            <div className="p-4 border border-red rounded-[var(--radius)] bg-code-bg text-red font-mono text-sm">
              Run not found or backend unreachable: {String(error)}
            </div>
          ) : isLoading || !data ? (
            <div className="text-subtle font-mono text-sm">Loading…</div>
          ) : isQuality ? (
            <QualityRunBody
              run={data}
              results={results}
              events={events}
              pipeline={pipeline}
            />
          ) : (
            <TransformRunBody
              run={data}
              runId={id}
              results={results}
              events={events}
              destination={destination}
              pipeline={pipeline}
            />
          )}
        </div>
      </div>
    </>
  );
}

function RunDetailGate() {
  return useSearchParams().get("id") ? <RunDetail /> : <MissingParam what="run" />;
}

export default withSuspense(RunDetailGate);
