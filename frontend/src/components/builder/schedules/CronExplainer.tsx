import { useMemo } from "react";
import { readCron, nextFireTimes } from "./cron";

/**
 * What the cron expression actually means, updated as you type.
 *
 * The friendly tabs explain themselves. Custom is a text box where `0 5 * * *`
 * and `0 * 5 * *` differ by one character and by a factor of twenty-four in
 * how often the pipeline runs — and the only feedback today is a server-side
 * validity check, which both spellings pass. You find out from stale data days
 * later.
 *
 * So: a plain-English reading plus the real next fire times. The times are the
 * part that catches mistakes the sentence doesn't; "on the 1st of the month"
 * sounds right until the preview says the next run is in five weeks.
 *
 * Evaluated in the schedule's timezone, matching croniter on the backend,
 * which stays the authority on whether an expression is accepted at all.
 */
export function CronExplainer({ expr, timezone }: { expr: string; timezone: string }) {
  const reading = useMemo(() => readCron(expr), [expr]);

  // Recomputed only when the expression or zone changes — not on a timer.
  // A preview that quietly advances while you read it is harder to trust
  // than one pinned to the moment you typed.
  const upcoming = useMemo(
    () => (reading.fields ? nextFireTimes(expr, timezone, 3) : []),
    [expr, timezone, reading.fields],
  );

  if (reading.problem) {
    return <div className="mt-1.5 text-[12px] text-red">{reading.problem}</div>;
  }
  if (!reading.text) return null;

  return (
    <div className="mt-1.5 space-y-1.5">
      <div className="text-[12.5px] text-text">{reading.text}</div>

      {reading.dayOrCaveat && (
        <div className="text-[11.5px] text-gold">
          Day-of-month and day-of-week are both set. Cron treats these as{" "}
          <strong className="font-medium">or</strong>, not and — this fires on either, which is
          usually more often than intended.
        </div>
      )}

      {upcoming.length > 0 && (
        <div className="font-mono text-[11px] text-subtle">
          <span className="tracking-[0.15em] uppercase text-[10px]">Next</span>{" "}
          {upcoming
            .map((d) =>
              d.toLocaleString(undefined, {
                timeZone: timezone,
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
                hour12: false,
              }),
            )
            .join("  ·  ")}
        </div>
      )}
    </div>
  );
}
