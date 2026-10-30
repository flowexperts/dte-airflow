import { useEffect, useState } from "react";
import useSWR from "swr";
import { CronExplainer } from "./CronExplainer";
import { createPortal } from "react-dom";
import { portalHost } from "@/components/ui/portal-host";
import { Button, Dropdown, Field, Input, Segmented } from "@/components/ui";
import {
  ApiError,
  listEvalSets,
  putSchedule,
  type EvalSet,
  type OverlapPolicy,
  type PipelineParam,
  type Schedule,
  type ScheduleWriteRequest,
} from "@/lib/api";
import {
  browserTimezone,
  composeCron,
  parseCron,
  timezoneOptions,
  WEEKDAY_LABELS,
  type ScheduleFormState,
  type ScheduleMode,
} from "./cron";

const MODE_OPTIONS: { value: ScheduleMode; label: string }[] = [
  { value: "hourly", label: "Hourly" },
  { value: "daily", label: "Daily" },
  { value: "weekly", label: "Weekly" },
  { value: "custom", label: "Custom" },
];

const OVERLAP_OPTIONS: { value: OverlapPolicy; label: string }[] = [
  { value: "skip", label: "Skip" },
  { value: "allow", label: "Allow" },
];

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

/** Errors from `POST/PUT /api/schedules` are either a plain string, the
 *  `{code: "invalid_cron_expression" | "invalid_timezone", message}` shape
 *  from `_compute_next_run_at`, or `ParamValidationError.payload()`
 *  (`{code: "param_validation_error", param, expected_type, got, message}`).
 *  We don't reimplement cron validation client-side — this just renders
 *  whatever the backend (croniter, the authority) says. */
function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const raw = e.rawDetail;
    if (raw && typeof raw === "object" && "message" in raw) {
      return String((raw as { message: unknown }).message);
    }
    return e.detail;
  }
  return e instanceof Error ? e.message : String(e);
}

export function ScheduleForm({
  pipelineId,
  pipelineParams,
  pipelineType,
  schedule,
  open,
  onClose,
  onSaved,
}: {
  pipelineId: string;
  /** `"eval"` swaps in the corpus picker and makes it mandatory — the
   *  backend applies the same rule, so omitting it here would just move
   *  the 422 from a disabled button to a failed save. */
  pipelineType?: string | undefined;
  /** Declared trigger-time inputs on the pipeline — required, no-default
   *  ones must be collected here or the backend 422s at create time
   *  (`_validate_params` in `dte/api/routes/schedules.py`). */
  pipelineParams: PipelineParam[] | undefined;
  /** Present → edit; absent → create. */
  schedule?: Schedule | null;
  open: boolean;
  onClose: () => void;
  onSaved: (s: Schedule) => void;
}) {
  const declaredParams = pipelineParams ?? [];
  const [form, setForm] = useState<ScheduleFormState>(() =>
    schedule
      ? { ...parseCron(schedule.cron_expr) }
      : { mode: "daily", minute: 0, hour: 2, weekday: 1, custom: "0 2 * * *" },
  );
  const [timezone, setTimezone] = useState(() => schedule?.timezone ?? browserTimezone());
  const [paramValues, setParamValues] = useState<Record<string, string>>(() => {
    const seed: Record<string, string> = {};
    for (const p of declaredParams) seed[p.name] = schedule?.params?.[p.name] ?? "";
    return seed;
  });
  const [overlap, setOverlap] = useState<OverlapPolicy>(schedule?.overlap ?? "skip");
  const [evalSetId, setEvalSetId] = useState<string>(schedule?.eval_set_id ?? "");
  const [enabled, setEnabled] = useState<boolean>(schedule?.enabled ?? true);
  const [retries, setRetries] = useState<number>(schedule?.retries ?? 0);
  const [retryDelayS, setRetryDelayS] = useState<number>(schedule?.retry_delay_s ?? 300);
  const [timeoutMin, setTimeoutMin] = useState<string>(schedule?.timeout_s ? String(schedule.timeout_s / 60) : "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [mounted, setMounted] = useState(false);

  // Keyed `null` for non-eval pipelines so the list is never fetched for
  // the ~all schedules that can't use it. Declared above the `!open`
  // early return — hooks can't sit behind a conditional.
  const { data: evalSets } = useSWR<EvalSet[]>(
    pipelineType === "eval" ? ["eval-sets", "schedule-form"] : null,
    () => listEvalSets(),
  );

  useEffect(() => setMounted(true), []);

  // Re-seed on open — mirrors ParamsModal's guarded re-sync so switching
  // which schedule is being edited doesn't leak stale state across opens.
  useEffect(() => {
    if (!open) return;
    setForm(schedule ? { ...parseCron(schedule.cron_expr) } : { mode: "daily", minute: 0, hour: 2, weekday: 1, custom: "0 2 * * *" });
    setTimezone(schedule?.timezone ?? browserTimezone());
    const seed: Record<string, string> = {};
    for (const p of declaredParams) seed[p.name] = schedule?.params?.[p.name] ?? "";
    setParamValues(seed);
    setOverlap(schedule?.overlap ?? "skip");
    setEvalSetId(schedule?.eval_set_id ?? "");
    setEnabled(schedule?.enabled ?? true);
    setRetries(schedule?.retries ?? 0);
    setRetryDelayS(schedule?.retry_delay_s ?? 300);
    setTimeoutMin(schedule?.timeout_s ? String(schedule.timeout_s / 60) : "");
    setErr(null);
    setBusy(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open || !mounted) return null;

  const cronExpr = composeCron(form);

  const missingRequired = declaredParams.filter(
    (p) => p.required !== false && (p.default == null || p.default === "") && (paramValues[p.name] ?? "") === "",
  );
  const isEval = pipelineType === "eval";
  const submittable =
    cronExpr.trim() !== "" && missingRequired.length === 0 && (!isEval || evalSetId !== "");

  const submit = async () => {
    setBusy(true);
    setErr(null);
    const params: Record<string, string> = {};
    for (const p of declaredParams) {
      const raw = paramValues[p.name] ?? "";
      if (raw === "" && (p.required === false || (p.default ?? "") !== "")) continue;
      params[p.name] = raw;
    }
    const body: ScheduleWriteRequest = {
      cron_expr: cronExpr,
      timezone,
      params,
      enabled,
      overlap,
      retries,
      retry_delay_s: retryDelayS,
      timeout_s: timeoutMin.trim() === "" ? null : Math.round(Number(timeoutMin) * 60),
      // Only ever sent for eval pipelines: the backend rejects it on any
      // other type rather than quietly ignoring it.
      ...(isEval ? { eval_set_id: evalSetId } : {}),
    };
    try {
      const saved = await putSchedule(pipelineId, body);
      onSaved(saved);
      onClose();
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="w-[560px] max-h-[calc(100vh-3rem)] overflow-y-auto rounded-md border border-border bg-surface p-5 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 text-sm font-medium">
          {schedule ? "Edit schedule" : "New schedule"}
        </div>

        <div className="space-y-4">
          <Field label="Frequency">
            <Segmented value={form.mode} onChange={(mode) => setForm((f) => ({ ...f, mode }))} options={MODE_OPTIONS} />
          </Field>

          {form.mode === "hourly" && (
            <Field label="At minute" hint="Runs every hour, at this minute past the hour.">
              <Input
                type="number"
                min={0}
                max={59}
                value={form.minute}
                onChange={(e) =>
                  setForm((f) => ({ ...f, minute: clamp(Number(e.target.value), 0, 59) }))
                }
                className="w-24"
              />
            </Field>
          )}

          {form.mode === "daily" && (
            <Field label="At time">
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  min={0}
                  max={23}
                  value={form.hour}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, hour: clamp(Number(e.target.value), 0, 23) }))
                  }
                  className="w-20"
                />
                <span className="text-subtle text-[13px]">:</span>
                <Input
                  type="number"
                  min={0}
                  max={59}
                  value={form.minute}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, minute: clamp(Number(e.target.value), 0, 59) }))
                  }
                  className="w-20"
                />
                <span className="font-mono text-[11px] text-subtle">
                  {pad2(form.hour)}:{pad2(form.minute)}
                </span>
              </div>
            </Field>
          )}

          {form.mode === "weekly" && (
            <Field label="On day, at time">
              <div className="flex items-center gap-2">
                <Dropdown<string>
                  value={String(form.weekday)}
                  onChange={(v) => setForm((f) => ({ ...f, weekday: Number(v) }))}
                  options={WEEKDAY_LABELS.map((label, i) => ({ value: String(i), label }))}
                  className="w-36"
                />
                <Input
                  type="number"
                  min={0}
                  max={23}
                  value={form.hour}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, hour: clamp(Number(e.target.value), 0, 23) }))
                  }
                  className="w-20"
                />
                <span className="text-subtle text-[13px]">:</span>
                <Input
                  type="number"
                  min={0}
                  max={59}
                  value={form.minute}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, minute: clamp(Number(e.target.value), 0, 59) }))
                  }
                  className="w-20"
                />
              </div>
            </Field>
          )}

          {form.mode === "custom" ? (
            /* No "Composed cron" echo here — on Custom it restated the box
               directly above it, character for character. The explainer is
               the useful readback; the raw string is already on screen. */
            <Field label="Cron expression" hint="Standard 5-field cron. Validated server-side.">
              <Input
                value={form.custom}
                onChange={(e) => setForm((f) => ({ ...f, custom: e.target.value }))}
                placeholder="0 2 * * *"
                className="font-mono"
              />
              <CronExplainer expr={cronExpr} timezone={timezone} />
            </Field>
          ) : (
            /* On the friendly tabs the cron string is derived and otherwise
               invisible, so it is worth showing alongside the reading. */
            <Field label="Composed cron" hint="What actually gets saved.">
              <div className="font-mono text-[12px] text-text bg-bg border border-border rounded-[var(--radius)] px-2.5 py-1.5">
                {cronExpr || "—"}
              </div>
              <CronExplainer expr={cronExpr} timezone={timezone} />
            </Field>
          )}

          <Field label="Timezone" hint="Defaults to your browser's timezone, not UTC.">
            <Dropdown<string>
              value={timezone}
              onChange={setTimezone}
              options={timezoneOptions().map((tz) => ({ value: tz, label: tz }))}
            />
          </Field>

          {schedule?.next_run_at && (
            <Field label="Next run">
              <div className="font-mono text-[12px] text-text">
                {new Date(schedule.next_run_at).toLocaleString(undefined, { timeZoneName: "short" })}
              </div>
            </Field>
          )}

          {declaredParams.length > 0 && (
            <Field label="Params" hint="Required inputs with no default must be filled in — the pipeline will fail every run otherwise.">
              <div className="space-y-2">
                {declaredParams.map((p) => {
                  const isRequired = p.required !== false && (p.default == null || p.default === "");
                  return (
                    <div key={p.name} className="grid grid-cols-[120px_1fr] gap-2 items-center">
                      <div className="text-[12px] font-mono text-muted">
                        {p.name}
                        {isRequired && <span className="text-red">*</span>}
                      </div>
                      <Input
                        value={paramValues[p.name] ?? ""}
                        onChange={(e) =>
                          setParamValues((s) => ({ ...s, [p.name]: e.target.value }))
                        }
                        placeholder={p.default ?? p.type}
                      />
                    </div>
                  );
                })}
              </div>
            </Field>
          )}

          {isEval && (
            <Field
              label="Score against"
              hint="The labeled corpus this nightly run is scored on. A drop in
                    macro-F1 at an unchanged config is how provider drift
                    surfaces — without a corpus there is nothing to compare."
            >
              <Dropdown
                value={evalSetId}
                onChange={setEvalSetId}
                placeholder={
                  evalSets === undefined
                    ? "Loading eval sets…"
                    : evalSets.length === 0
                      ? "No eval sets — create one first"
                      : "— select a corpus —"
                }
                options={(evalSets ?? []).map((s) => ({
                  value: s.id,
                  label: `${s.name} · ${s.example_count ?? 0} labeled`,
                }))}
              />
            </Field>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Field label="On overlap" hint="If the previous run is still going.">
              <Segmented value={overlap} onChange={setOverlap} options={OVERLAP_OPTIONS} />
            </Field>
            <Field label="Status">
              <Segmented
                value={enabled ? "enabled" : "disabled"}
                onChange={(v) => setEnabled(v === "enabled")}
                options={[
                  { value: "enabled", label: "Enabled" },
                  { value: "disabled", label: "Disabled" },
                ]}
              />
            </Field>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <Field label="Retries" hint="Off for append destinations.">
              <Input
                type="number"
                min={0}
                max={10}
                value={retries}
                onChange={(e) => setRetries(clamp(Number(e.target.value), 0, 10))}
              />
            </Field>
            <Field label="Retry after (s)">
              <Input
                type="number"
                min={10}
                value={retryDelayS}
                onChange={(e) => setRetryDelayS(Math.max(10, Number(e.target.value) || 10))}
              />
            </Field>
            <Field label="Timeout (min)" hint="Blank = none.">
              <Input
                type="number"
                min={1}
                value={timeoutMin}
                onChange={(e) => setTimeoutMin(e.target.value)}
                placeholder="none"
              />
            </Field>
          </div>

        </div>

        {err && (
          <div className="mt-4 rounded border border-red/40 bg-red/10 p-2 font-mono text-[11px] text-red">
            {err}
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" disabled={busy || !submittable} onClick={submit}>
            {busy ? "Saving…" : schedule ? "Save changes" : "Create schedule"}
          </Button>
        </div>
      </div>
    </div>,
    portalHost(),
  );
}

function clamp(n: number, min: number, max: number): number {
  if (Number.isNaN(n)) return min;
  return Math.min(max, Math.max(min, n));
}
