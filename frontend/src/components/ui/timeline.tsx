import { cn } from "@/lib/cn";
import type { ReactNode } from "react";

export function Timeline({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "border border-border rounded-[var(--radius)] bg-surface overflow-hidden",
        className,
      )}
    >
      {children}
    </div>
  );
}

type Tone = "default" | "warn" | "err";

const dotStyles: Record<Tone, { bg: string; ring: string }> = {
  default: { bg: "var(--green)", ring: "color-mix(in srgb, var(--green) 20%, transparent)" },
  warn: { bg: "var(--gold)", ring: "color-mix(in srgb, var(--gold) 20%, transparent)" },
  err: { bg: "var(--red)", ring: "color-mix(in srgb, var(--red) 20%, transparent)" },
};

export function TimelineRow({
  time,
  message,
  duration,
  tone = "default",
  className,
}: {
  time: ReactNode;
  message: ReactNode;
  duration?: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  const s = dotStyles[tone];
  return (
    <div
      className={cn(
        "grid grid-cols-[120px_30px_1fr_60px] items-center px-4 py-2.5 border-b border-border last:border-b-0 font-mono text-[12px] hover:bg-hover transition-colors",
        className,
      )}
    >
      <span className="text-subtle text-[11.5px] tracking-[0.03em]">{time}</span>
      <span
        className="size-1.5 rounded-full"
        style={{
          background: s.bg,
          boxShadow: `0 0 0 2px ${s.ring}`,
        }}
      />
      <span className="font-[family-name:var(--font-ui)] text-[13px] text-text">{message}</span>
      <span className="text-subtle text-[11.5px] text-right">{duration}</span>
    </div>
  );
}

export function InlineCode({ children }: { children: ReactNode }) {
  return (
    <code className="font-mono text-[11.5px] text-muted bg-code-bg px-1.5 py-px rounded-sm border border-border">
      {children}
    </code>
  );
}
