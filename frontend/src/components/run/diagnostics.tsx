"use client";

import { useState } from "react";
import { InlineCode, Panel } from "@/components/ui";
import type { RunEvent } from "@/lib/api";
import { toneVar, type Tone } from "./helpers";

function eventTone(status: RunEvent["status"] | undefined): Tone {
  if (status === "failed") return "err";
  if (status === "started") return "warn";
  return "ok";
}

function duration(event: RunEvent | undefined): string {
  if (!event) return "";
  if (event.started_at && event.finished_at) {
    const ms = Math.max(
      0,
      new Date(event.finished_at).getTime() - new Date(event.started_at).getTime(),
    );
    return `${ms}ms`;
  }
  return event.status === "started" ? "…" : "—";
}

function TimelineRow({ index, event }: { index: number; event: RunEvent | undefined }) {
  const started = event?.started_at ? new Date(event.started_at) : null;
  return (
    <div className="grid grid-cols-[90px_14px_1fr_auto] items-center gap-2.5 py-2">
      <span className="font-mono text-[11.5px] text-subtle tabular-nums">
        {started ? started.toLocaleTimeString() : "—"}
      </span>
      <span
        className="size-1.5 rounded-full justify-self-center"
        style={{ background: toneVar[eventTone(event?.status)] }}
      />
      <span className="text-[12.5px] text-text">
        {event ? (
          <>
            <InlineCode>{event.op}</InlineCode> step {index} {event.status}
            {event.message ? ` — ${event.message}` : ""}
          </>
        ) : (
          <>step {index}</>
        )}
      </span>
      <span className="font-mono text-[11.5px] text-subtle tabular-nums">
        {duration(event)}
      </span>
    </div>
  );
}

function Sql({ label, sql }: { label: string; sql: string }) {
  return (
    <div className="mb-3 last:mb-0">
      <div className="font-mono text-[11px] tracking-[0.1em] uppercase text-subtle mb-1.5">
        {label}
      </div>
      <div className="bg-code-bg border border-border rounded-[var(--radius)] overflow-auto max-h-[320px]">
        <pre className="p-3 font-mono text-[12px] text-text whitespace-pre">{sql}</pre>
      </div>
    </div>
  );
}

/** Engineering detail — timeline + compiled SQL — demoted below the fold but
 *  open by default. It is for debugging, never for reading the outcome. */
export function Diagnostics({
  events,
  stepSqls,
  finalSql,
  sqlTabLabel,
}: {
  events: RunEvent[];
  stepSqls: Map<number, string>;
  finalSql: string | null;
  sqlTabLabel: string;
}) {
  const [open, setOpen] = useState(true);
  const [tab, setTab] = useState<"timeline" | "sql">("timeline");

  const indices = new Set<number>(events.map((e) => e.step_index));
  stepSqls.forEach((_, i) => indices.add(i));
  const sorted = [...indices].sort((a, b) => a - b);
  const eventByIndex = new Map(events.map((e) => [e.step_index, e]));
  const hasSql = finalSql !== null || stepSqls.size > 0;

  if (sorted.length === 0 && !hasSql) return null;

  return (
    <Panel>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-hover transition-colors text-left"
      >
        <span className="flex items-center gap-2.5">
          <span
            className={`text-[9px] text-muted inline-block transition-transform ${open ? "rotate-90" : ""}`}
          >
            ▶
          </span>
          <span className="text-[15px] font-medium text-text">Diagnostics</span>
          <span className="text-[12px] text-subtle">
            execution timeline &amp; compiled SQL — {sorted.length} step
            {sorted.length === 1 ? "" : "s"}
          </span>
        </span>
        <span className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle">
          for debugging
        </span>
      </button>

      {open && (
        <div className="border-t border-border px-4 pb-4">
          <div className="flex gap-1 my-3">
            {(
              [
                ["timeline", "Timeline"],
                ["sql", sqlTabLabel],
              ] as const
            ).map(([key, label]) =>
              key === "sql" && !hasSql ? null : (
                <button
                  key={key}
                  type="button"
                  onClick={() => setTab(key)}
                  className={`font-mono text-[11.5px] tracking-[0.03em] px-3 py-1.5 rounded-[var(--radius)] border transition-colors ${
                    tab === key
                      ? "bg-text text-bg border-text"
                      : "bg-surface-2 text-subtle border-border hover:text-text"
                  }`}
                >
                  {label}
                </button>
              ),
            )}
          </div>

          {tab === "timeline" &&
            (sorted.length === 0 ? (
              <div className="py-6 text-center text-subtle text-sm">
                No step events recorded.
              </div>
            ) : (
              sorted.map((i) => (
                <TimelineRow key={i} index={i} event={eventByIndex.get(i)} />
              ))
            ))}

          {tab === "sql" && hasSql && (
            <div>
              {finalSql && <Sql label="Final query" sql={finalSql} />}
              {[...stepSqls.entries()]
                .sort((a, b) => a[0] - b[0])
                .map(([i, sql]) => (
                  <Sql key={i} label={`Step ${i}`} sql={sql} />
                ))}
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
