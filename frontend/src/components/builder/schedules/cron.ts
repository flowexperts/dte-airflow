/**
 * Cron composer for the schedule form's Hourly / Daily / Weekly / Custom
 * tabs (plan 047 task 7). This is deliberately *not* a cron parser/validator
 * — `croniter` on the backend is the authority (see `ScheduleWriteRequest`
 * validation in `dte/api/routes/schedules.py`). Client-side we only need to:
 *
 *  1. Compose a standard 5-field cron string from the friendly controls.
 *  2. Best-effort recognise a cron string produced by one of those three
 *     shapes, so editing an existing schedule opens on the right tab instead
 *     of always falling back to Custom. Anything that doesn't match one of
 *     the three exact shapes lands on Custom with the raw string intact —
 *     never silently rewritten.
 *
 * Weekday numbering matches cron/croniter: 0 = Sunday .. 6 = Saturday.
 */

export type ScheduleMode = "hourly" | "daily" | "weekly" | "custom";

export interface ScheduleFormState {
  mode: ScheduleMode;
  minute: number; // 0-59
  hour: number; // 0-23
  weekday: number; // 0-6, Sunday = 0
  custom: string;
}

export const WEEKDAY_LABELS = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

export function defaultScheduleFormState(): ScheduleFormState {
  return { mode: "daily", minute: 0, hour: 2, weekday: 1, custom: "0 2 * * *" };
}

export function composeCron(state: ScheduleFormState): string {
  switch (state.mode) {
    case "hourly":
      return `${state.minute} * * * *`;
    case "daily":
      return `${state.minute} ${state.hour} * * *`;
    case "weekly":
      return `${state.minute} ${state.hour} * * ${state.weekday}`;
    case "custom":
      return state.custom;
  }
}

/** Best-effort inverse of `composeCron`. Falls back to `{ mode: "custom" }`
 *  with the raw expr preserved when the shape doesn't match one of the
 *  three friendly forms exactly (e.g. `*\/15 * * * *`, ranges, lists). */
export function parseCron(expr: string): ScheduleFormState {
  const parts = expr.trim().split(/\s+/);
  const fallback: ScheduleFormState = {
    ...defaultScheduleFormState(),
    mode: "custom",
    custom: expr,
  };
  if (parts.length !== 5) return fallback;
  const [min, hr, dom, mon, dow] = parts;

  const isInt = (s: string) => /^\d+$/.test(s);

  if (min !== undefined && isInt(min) && hr === "*" && dom === "*" && mon === "*" && dow === "*") {
    const minute = Number(min);
    if (minute >= 0 && minute <= 59) {
      return { ...fallback, mode: "hourly", minute, custom: expr };
    }
  }

  if (
    min !== undefined && hr !== undefined &&
    isInt(min) && isInt(hr) && dom === "*" && mon === "*" && dow === "*"
  ) {
    const minute = Number(min);
    const hour = Number(hr);
    if (minute >= 0 && minute <= 59 && hour >= 0 && hour <= 23) {
      return { ...fallback, mode: "daily", minute, hour, custom: expr };
    }
  }

  if (
    min !== undefined && hr !== undefined && dow !== undefined &&
    isInt(min) && isInt(hr) && dom === "*" && mon === "*" && isInt(dow)
  ) {
    const minute = Number(min);
    const hour = Number(hr);
    const weekday = Number(dow);
    if (minute >= 0 && minute <= 59 && hour >= 0 && hour <= 23 && weekday >= 0 && weekday <= 6) {
      return { ...fallback, mode: "weekly", minute, hour, weekday, custom: expr };
    }
  }

  return fallback;
}

export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

/** Common IANA zones for the picker, browser zone first (deduped). Not
 *  exhaustive — `Intl.supportedValuesOf("timeZone")` backs a "more…" case
 *  when the runtime supports it. */
export function timezoneOptions(): string[] {
  const preferred = [
    browserTimezone(),
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Asia/Kolkata",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Australia/Sydney",
  ];
  let all = preferred;
  try {
    if (typeof Intl.supportedValuesOf === "function") {
      const supported: string[] = Intl.supportedValuesOf("timeZone");
      all = [...preferred, ...supported];
    }
  } catch {
    // Intl.supportedValuesOf unavailable — stick with the curated list.
  }
  return Array.from(new Set(all));
}
