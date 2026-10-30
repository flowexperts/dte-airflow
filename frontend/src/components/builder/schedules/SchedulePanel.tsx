import { useState } from "react";
import useSWR from "swr";
import { Button, Panel, PanelHead, Pill } from "@/components/ui";
import {
  deleteSchedule,
  getSchedule,
  putSchedule,
  type PipelineParam,
  type Schedule,
} from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";
import { ScheduleForm } from "./ScheduleForm";

function formatNextRun(iso: string | null): string {
  if (!iso) return "—";
  // `next_run_at` is UTC; render it in the viewer's zone. `schedule.timezone`
  // is what the *cron* is evaluated against, not what the viewer reads in.
  return new Date(iso).toLocaleString(undefined, { timeZoneName: "short" });
}

/** The pipeline's one schedule (plan 068) — it is the cron of the pipeline's
 *  one Airflow DAG. Every change is a pipeline revision. */
export function SchedulePanel({
  pipelineId,
  pipelineParams,
  pipelineType,
}: {
  pipelineId: string;
  pipelineParams: PipelineParam[] | undefined;
  pipelineType?: string | undefined;
}) {
  const {
    data: schedule,
    error,
    isLoading,
    mutate,
  } = useSWR(["pipeline-schedule", pipelineId], () => getSchedule(pipelineId));
  const { can } = usePermissions();
  const canWrite = can("pipeline:trigger");
  const [formOpen, setFormOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const act = async (fn: () => Promise<Schedule | null>) => {
    setBusy(true);
    try {
      mutate(await fn(), { revalidate: false });
    } finally {
      setBusy(false);
    }
  };

  const toggleEnabled = (s: Schedule) =>
    act(() => putSchedule(pipelineId, { ...s, enabled: !s.enabled }));

  const remove = (s: Schedule) => {
    // Retries and the timeout live on the schedule and cover manual runs too,
    // so removing it switches them off as well (plan 070). Notifications don't.
    const alsoLost =
      s.retries > 0 || s.timeout_s != null
        ? "\n\nThis also turns off retries and the timeout, for manual runs too."
        : "";
    if (!window.confirm(`Remove schedule ${s.cron_expr} (${s.timezone})?${alsoLost}`)) return;
    act(async () => {
      await deleteSchedule(pipelineId);
      return null;
    });
  };

  return (
    <Panel>
      <PanelHead label="Schedule" />
      {isLoading && <div className="text-[12px] text-subtle px-3.5 py-4">Loading schedule…</div>}
      {error && (
        <div className="text-[12px] text-red px-3.5 py-4">Couldn&apos;t load the schedule.</div>
      )}
      {!isLoading && !error && !schedule && (
        <div className="text-[12px] text-subtle px-3.5 py-4">
          No schedule — this pipeline only runs on manual trigger.
        </div>
      )}
      {schedule && (
        <div className="grid grid-cols-[1fr_auto] gap-2.5 items-center px-3.5 py-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[13px] text-text">{schedule.cron_expr}</span>
              <span className="font-mono text-[11px] text-subtle">{schedule.timezone}</span>
              <Pill status={schedule.enabled ? "ok" : "pending"}>
                {schedule.enabled ? "Enabled" : "Disabled"}
              </Pill>
              {schedule.overlap === "allow" && (
                <span className="font-mono text-[10px] uppercase tracking-wide text-subtle">
                  overlap: allow
                </span>
              )}
            </div>
            <div className="mt-1 font-mono text-[11px] text-subtle">
              Next run: {formatNextRun(schedule.next_run_at)}
            </div>
            <div className="mt-0.5 font-mono text-[11px] text-subtle">
              On failure: {failureSummary(schedule)}
            </div>
          </div>
          {canWrite && (
            <div className="flex items-center gap-1.5 shrink-0">
              <Button size="sm" onClick={() => toggleEnabled(schedule)} disabled={busy}>
                {schedule.enabled ? "Disable" : "Enable"}
              </Button>
              <Button size="sm" onClick={() => setFormOpen(true)} disabled={busy}>
                Edit
              </Button>
              <Button size="sm" variant="ghost" onClick={() => remove(schedule)} disabled={busy}>
                Remove
              </Button>
            </div>
          )}
        </div>
      )}
      {canWrite && !isLoading && !error && !schedule && (
        <button
          type="button"
          onClick={() => setFormOpen(true)}
          className="w-full text-center py-3 px-3.5 border-t border-dashed border-border font-medium text-xs text-subtle hover:text-accent hover:bg-[color:var(--accent-tint)] transition-colors"
        >
          <span className="text-accent font-bold mr-1">+</span> Set schedule
        </button>
      )}
      <ScheduleForm
        pipelineId={pipelineId}
        pipelineParams={pipelineParams}
        pipelineType={pipelineType}
        schedule={schedule ?? null}
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSaved={(s) => mutate(s, { revalidate: false })}
      />
    </Panel>
  );
}

function failureSummary(s: Schedule): string {
  const parts = [
    s.retries > 0 ? `retry ${s.retries}× after ${s.retry_delay_s}s` : "no retries",
    ...(s.timeout_s != null ? [`timeout ${Math.round(s.timeout_s / 60)} min`] : []),
  ];
  return parts.join(" · ");
}
