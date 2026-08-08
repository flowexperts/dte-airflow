"use client";

import { useState } from "react";
import useSWR from "swr";
import { Button, Panel, PanelHead, Pill } from "@/components/ui";
import {
  deleteSchedule,
  listSchedulesForPipeline,
  updateSchedule,
  type PipelineParam,
  type Schedule,
} from "@/lib/api";
import { usePermissions } from "@/lib/use-permissions";
import { ScheduleForm } from "./ScheduleForm";

function formatNextRun(iso: string | null): string {
  if (!iso) return "—";
  // `next_run_at` is stored UTC; `toLocaleString` renders it in the
  // viewer's local timezone — the "trust the cron" requirement from the
  // plan. `schedule.timezone` is what the *cron* is evaluated against,
  // not necessarily what the viewer wants to read it in.
  return new Date(iso).toLocaleString(undefined, { timeZoneName: "short" });
}

function ScheduleRow({
  schedule,
  pipelineParams,
  onChanged,
  onDeleted,
  canWrite,
}: {
  schedule: Schedule;
  pipelineParams: PipelineParam[] | undefined;
  onChanged: (s: Schedule) => void;
  onDeleted: (id: string) => void;
  canWrite: boolean;
}) {
  const [editOpen, setEditOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const toggleEnabled = async () => {
    setBusy(true);
    try {
      const saved = await updateSchedule(schedule.id, {
        cron_expr: schedule.cron_expr,
        timezone: schedule.timezone,
        params: schedule.params,
        enabled: !schedule.enabled,
        overlap: schedule.overlap,
      });
      onChanged(saved);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete schedule ${schedule.cron_expr} (${schedule.timezone})?`)) return;
    setBusy(true);
    try {
      await deleteSchedule(schedule.id);
      onDeleted(schedule.id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid-cols-[1fr_auto] gap-2.5 items-center px-3.5 py-3 border-b border-border last:border-b-0 hover:bg-hover transition-colors">
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
          {schedule.last_fired_at && (
            <> · Last fired: {new Date(schedule.last_fired_at).toLocaleString()}</>
          )}
        </div>
      </div>
      {canWrite && (
        <div className="flex items-center gap-1.5 shrink-0">
          <Button size="sm" onClick={toggleEnabled} disabled={busy}>
            {schedule.enabled ? "Disable" : "Enable"}
          </Button>
          <Button size="sm" onClick={() => setEditOpen(true)} disabled={busy}>
            Edit
          </Button>
          <Button size="sm" variant="ghost" onClick={remove} disabled={busy}>
            Delete
          </Button>
        </div>
      )}
      <ScheduleForm
        pipelineId={schedule.pipeline_id}
        pipelineParams={pipelineParams}
        schedule={schedule}
        open={editOpen}
        onClose={() => setEditOpen(false)}
        onSaved={onChanged}
      />
    </div>
  );
}

/** Recurring-trigger panel on the pipeline detail page (plan 047 task 7).
 *  Sibling of Output / Recent runs — composed as a client component since
 *  every row here owns event handlers (enable toggle, edit, delete), which
 *  a server component cannot pass down (see CLAUDE.md "Server vs client
 *  component discipline"). */
export function SchedulePanel({
  pipelineId,
  pipelineParams,
}: {
  pipelineId: string;
  pipelineParams: PipelineParam[] | undefined;
}) {
  const { data, error, isLoading, mutate } = useSWR(
    ["pipeline-schedules", pipelineId],
    () => listSchedulesForPipeline(pipelineId),
  );
  const { can } = usePermissions();
  const canWrite = can("pipeline:trigger");
  const [createOpen, setCreateOpen] = useState(false);

  const schedules = data ?? [];

  const handleChanged = (s: Schedule) => {
    mutate((prev) => (prev ?? []).map((x) => (x.id === s.id ? s : x)), { revalidate: false });
  };
  const handleDeleted = (id: string) => {
    mutate((prev) => (prev ?? []).filter((x) => x.id !== id), { revalidate: false });
  };
  const handleCreated = (s: Schedule) => {
    mutate((prev) => [...(prev ?? []), s], { revalidate: false });
  };

  return (
    <Panel>
      <PanelHead label="Schedules" count={schedules.length} />
      {isLoading && (
        <div className="text-[12px] text-subtle px-3.5 py-4">Loading schedules…</div>
      )}
      {error && (
        <div className="text-[12px] text-red px-3.5 py-4">Couldn&apos;t load schedules.</div>
      )}
      {!isLoading && !error && schedules.length === 0 && (
        <div className="text-[12px] text-subtle px-3.5 py-4">
          No schedules yet — this pipeline only runs on manual trigger.
        </div>
      )}
      {schedules.map((s) => (
        <ScheduleRow
          key={s.id}
          schedule={s}
          pipelineParams={pipelineParams}
          onChanged={handleChanged}
          onDeleted={handleDeleted}
          canWrite={canWrite}
        />
      ))}
      {canWrite && (
        <button
          type="button"
          onClick={() => setCreateOpen(true)}
          className="w-full text-center py-3 px-3.5 border-t border-dashed border-border font-medium text-xs text-subtle hover:text-accent hover:bg-[color:var(--accent-tint)] transition-colors"
        >
          <span className="text-accent font-bold mr-1">+</span> Add schedule
        </button>
      )}
      <ScheduleForm
        pipelineId={pipelineId}
        pipelineParams={pipelineParams}
        schedule={null}
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSaved={handleCreated}
      />
    </Panel>
  );
}
