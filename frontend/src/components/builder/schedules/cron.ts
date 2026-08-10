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

// ---------------------------------------------------------------------------
// Live explainer for the Custom tab
//
// The friendly tabs explain themselves; Custom is a five-character-wide text
// box where a typo silently means "3am on the 5th of every month" instead of
// "every 5 minutes", and you find out days later when the data is stale. So
// Custom gets a running translation plus the actual next fire times.
//
// This is a *reader*, not a validator — croniter on the backend still has the
// final word, and a rejected expression must fail there rather than be
// quietly rewritten here. It covers the syntax croniter accepts for the five
// standard fields: `*`, integers, lists (`1,15`), ranges (`1-5`), and steps
// (`*./15`, `1-9/2`). Names (`MON`, `JAN`) and the non-standard `L`/`W`/`#`
// are reported as unreadable rather than guessed at.
// ---------------------------------------------------------------------------

interface FieldSpec {
  min: number;
  max: number;
  name: string;
}

const FIELDS: FieldSpec[] = [
  { min: 0, max: 59, name: "minute" },
  { min: 0, max: 23, name: "hour" },
  { min: 1, max: 31, name: "day of month" },
  { min: 1, max: 12, name: "month" },
  { min: 0, max: 6, name: "day of week" },
];

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/** Expand one cron field into the sorted set of values it matches.
 *  Returns null when the field uses syntax this reader doesn't cover. */
export function expandField(raw: string, spec: FieldSpec): number[] | null {
  const out = new Set<number>();
  for (const term of raw.split(",")) {
    if (term === "") return null;
    const [rangePart, stepPart, ...rest] = term.split("/");
    if (rest.length > 0 || rangePart === undefined) return null;

    let step = 1;
    if (stepPart !== undefined) {
      if (!/^\d+$/.test(stepPart)) return null;
      step = Number(stepPart);
      if (step < 1) return null;
    }

    let lo: number;
    let hi: number;
    if (rangePart === "*") {
      lo = spec.min;
      hi = spec.max;
    } else if (/^\d+$/.test(rangePart)) {
      lo = Number(rangePart);
      // A bare number with a step means "from here to the end" (croniter).
      hi = stepPart === undefined ? lo : spec.max;
    } else {
      const m = /^(\d+)-(\d+)$/.exec(rangePart);
      if (!m || m[1] === undefined || m[2] === undefined) return null;
      lo = Number(m[1]);
      hi = Number(m[2]);
    }
    if (lo < spec.min || hi > spec.max || lo > hi) return null;
    for (let v = lo; v <= hi; v += step) out.add(v);
  }
  return [...out].sort((a, b) => a - b);
}

export interface CronReading {
  /** Plain-English rendering, or null when the expression can't be read. */
  text: string | null;
  /** Why it can't be read — shown instead of the text. */
  problem: string | null;
  fields: {
    minute: number[];
    hour: number[];
    dayOfMonth: number[];
    month: number[];
    dayOfWeek: number[];
  } | null;
  /** True when day-of-month and day-of-week are both restricted. Cron ORs
   *  these two, which surprises nearly everyone, so it is called out. */
  dayOrCaveat: boolean;
}

const listOut = (xs: (string | number)[], join = "and"): string =>
  xs.length === 1
    ? String(xs[0])
    : `${xs.slice(0, -1).join(", ")} ${join} ${xs[xs.length - 1]}`;

const pad = (n: number) => String(n).padStart(2, "0");

/** Is this set every value in the field's range? */
const isFull = (vals: number[], spec: FieldSpec) =>
  vals.length === spec.max - spec.min + 1;

/** Detect an evenly-spaced set so `*./15` reads as "every 15 minutes"
 *  rather than "at minute 0, 15, 30 and 45". */
function evenStep(vals: number[], spec: FieldSpec): number | null {
  if (vals.length < 2 || vals[0] !== spec.min) return null;
  const step = (vals[1] as number) - (vals[0] as number);
  for (let i = 1; i < vals.length; i++) {
    if ((vals[i] as number) - (vals[i - 1] as number) !== step) return null;
  }
  // Must run to the end of the range, or it's a partial window not a cadence.
  if ((vals[vals.length - 1] as number) + step <= spec.max) return null;
  return step;
}

export function readCron(expr: string): CronReading {
  const empty: CronReading = {
    text: null,
    problem: null,
    fields: null,
    dayOrCaveat: false,
  };
  const trimmed = expr.trim();
  if (!trimmed) return { ...empty, problem: "Empty." };

  const parts = trimmed.split(/\s+/);
  if (parts.length !== 5) {
    return {
      ...empty,
      problem: `Needs 5 fields (minute hour day-of-month month day-of-week); got ${parts.length}.`,
    };
  }

  const expanded: number[][] = [];
  for (let i = 0; i < 5; i++) {
    const spec = FIELDS[i] as FieldSpec;
    const vals = expandField(parts[i] as string, spec);
    if (vals === null || vals.length === 0) {
      return {
        ...empty,
        problem: `Can't read the ${spec.name} field ("${parts[i]}"). Supported: * , - / and numbers ${spec.min}-${spec.max}.`,
      };
    }
    expanded.push(vals);
  }

  const [minute, hour, dom, month, dow] = expanded as [
    number[], number[], number[], number[], number[],
  ];
  const fields = {
    minute,
    hour,
    dayOfMonth: dom,
    month,
    dayOfWeek: dow,
  };

  const minSpec = FIELDS[0] as FieldSpec;
  const hourSpec = FIELDS[1] as FieldSpec;

  // --- time of day ---
  let when: string;
  const minStep = evenStep(minute, minSpec);
  const hourStep = evenStep(hour, hourSpec);

  if (isFull(minute, minSpec) && isFull(hour, hourSpec)) {
    when = "Every minute";
  } else if (isFull(minute, minSpec)) {
    when = `Every minute during ${listOut(hour.map((h) => `${pad(h)}:00`))}`;
  } else if (minStep !== null && minStep > 1 && isFull(hour, hourSpec)) {
    when = `Every ${minStep} minutes`;
  } else if (minStep !== null && minStep > 1) {
    when = `Every ${minStep} minutes during ${listOut(hour.map((h) => `${pad(h)}:00`))}`;
  } else if (isFull(hour, hourSpec)) {
    when =
      minute.length === 1
        ? `Every hour at :${pad(minute[0] as number)}`
        : `Every hour at ${listOut(minute.map((m) => `:${pad(m)}`))}`;
  } else if (hourStep !== null && hourStep > 1 && minute.length === 1) {
    when = `Every ${hourStep} hours, at :${pad(minute[0] as number)}`;
  } else if (
    // A contiguous block of hours is a working window, not a list of times:
    // "0 9-17 * * 1-5" is "every hour from 09:00 to 17:00", not "9 times a day".
    minute.length === 1 &&
    hour.length > 2 &&
    (hour[hour.length - 1] as number) - (hour[0] as number) === hour.length - 1
  ) {
    const m = pad(minute[0] as number);
    when = `Every hour from ${pad(hour[0] as number)}:${m} to ${pad(hour[hour.length - 1] as number)}:${m}`;
  } else {
    const times: string[] = [];
    for (const h of hour) for (const m of minute) times.push(`${pad(h)}:${pad(m)}`);
    when =
      times.length <= 6
        ? `At ${listOut(times)}`
        : `At ${times.length} times a day (${times.slice(0, 3).join(", ")}, …)`;
  }

  // --- which days ---
  const domFull = isFull(dom, FIELDS[2] as FieldSpec);
  const dowFull = isFull(dow, FIELDS[4] as FieldSpec);
  const monthFull = isFull(month, FIELDS[3] as FieldSpec);

  const dayParts: string[] = [];
  if (!dowFull) {
    dayParts.push(`on ${listOut(dow.map((d) => WEEKDAY_LABELS[d] ?? String(d)), "and")}`);
  }
  if (!domFull) {
    dayParts.push(`on the ${listOut(dom.map(ordinal))} of the month`);
  }
  if (!monthFull) {
    dayParts.push(`in ${listOut(month.map((m) => MONTH_NAMES[m - 1] ?? String(m)))}`);
  }
  if (dayParts.length === 0 && !when.startsWith("Every minute") && !when.startsWith("Every ")) {
    dayParts.push("every day");
  }

  const text = [when, ...dayParts].join(", ") + ".";

  return {
    text,
    problem: null,
    fields,
    // Cron ORs day-of-month with day-of-week when both are restricted.
    dayOrCaveat: !domFull && !dowFull,
  };
}

function ordinal(n: number): string {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] ?? s[v] ?? s[0] ?? "th");
}

/** The instant's wall-clock fields in an IANA zone. */
function zonedParts(d: Date, timeZone: string) {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
    weekday: "short",
    hour12: false,
  });
  const out: Record<string, string> = {};
  for (const p of fmt.formatToParts(d)) out[p.type] = p.value;
  const weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  return {
    year: Number(out.year),
    month: Number(out.month),
    day: Number(out.day),
    // Intl renders midnight as hour 24 in some zones with hour12:false.
    hour: Number(out.hour) % 24,
    minute: Number(out.minute),
    weekday: Math.max(0, weekdays.indexOf(out.weekday ?? "Sun")),
  };
}

/**
 * The next `count` fire times, evaluated against `timeZone`.
 *
 * Walks forward from now in the target zone, skipping by the largest unit
 * that already fails to match — so a "1st of January" expression converges in
 * a few hundred steps instead of half a million. Wall-clock evaluation in the
 * zone is what makes DST behave the way people expect: 2am daily stays 2am
 * local across the transition, matching croniter on the backend.
 */
export function nextFireTimes(
  expr: string,
  timeZone: string,
  count = 3,
  from: Date = new Date(),
): Date[] {
  const reading = readCron(expr);
  if (!reading.fields) return [];
  const { minute, hour, dayOfMonth, month, dayOfWeek } = reading.fields;
  const domFull = dayOfMonth.length === 31;
  const dowFull = dayOfWeek.length === 7;

  const out: Date[] = [];
  // Start at the next whole minute; a schedule never fires in the past.
  let cursor = new Date(Math.floor(from.getTime() / 60000) * 60000 + 60000);

  let guard = 0;
  const MAX_STEPS = 200_000; // ~4.5 months of minute steps in the worst case
  while (out.length < count && guard++ < MAX_STEPS) {
    let p;
    try {
      p = zonedParts(cursor, timeZone);
    } catch {
      return []; // unknown timezone — say nothing rather than guess
    }

    // Skips snap to the *start* of the next unit, never a flat +24h. A flat
    // day jump keeps the time-of-day phase and sails straight past a match:
    // from 03:58 today, "0 0 1 1 *" landed on 1 January at 03:58 and missed
    // that year's midnight entirely, reporting the year after.
    const toNextLocalMidnight = (24 * 60 - (p.hour * 60 + p.minute)) * 60_000;

    if (!month.includes(p.month)) {
      cursor = new Date(cursor.getTime() + toNextLocalMidnight);
      continue;
    }
    // Cron ORs day-of-month and day-of-week unless one of them is unrestricted.
    const domOk = dayOfMonth.includes(p.day);
    const dowOk = dayOfWeek.includes(p.weekday);
    const dayOk = domFull || dowFull ? domOk && dowOk : domOk || dowOk;
    if (!dayOk) {
      cursor = new Date(cursor.getTime() + toNextLocalMidnight);
      continue;
    }
    if (!hour.includes(p.hour)) {
      cursor = new Date(cursor.getTime() + 60_000 * (60 - p.minute));
      continue;
    }
    if (!minute.includes(p.minute)) {
      cursor = new Date(cursor.getTime() + 60_000);
      continue;
    }
    out.push(new Date(cursor));
    cursor = new Date(cursor.getTime() + 60_000);
  }
  return out;
}
