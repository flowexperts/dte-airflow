import type { ReactNode } from "react";
import { toneTint, toneVar, type Tone } from "./helpers";

const GLYPH: Record<Tone, string> = { ok: "✓", warn: "!", err: "×" };

/** The single fact that matters most about this run, stated first and stated
 *  once. Everything below the banner is supporting detail. */
export function VerdictBanner({
  tone,
  headline,
  sub,
  meta,
}: {
  tone: Tone;
  headline: ReactNode;
  sub?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <div
      className="flex gap-3.5 items-start rounded-[var(--radius)] px-4 py-3.5"
      style={{
        background: toneTint(tone, 9),
        border: `1px solid ${toneTint(tone, 38)}`,
      }}
    >
      <span
        className="shrink-0 size-7 rounded-full grid place-items-center text-[14px] font-semibold leading-none"
        style={{ background: toneVar[tone], color: "var(--bg)" }}
      >
        {GLYPH[tone]}
      </span>
      <div className="min-w-0">
        <strong className="block text-[14px] font-medium text-text">
          {headline}
        </strong>
        {sub && <span className="text-[13px] text-muted">{sub}</span>}
        {meta && (
          <div className="mt-1.5 font-mono text-[11.5px] text-subtle">{meta}</div>
        )}
      </div>
    </div>
  );
}
