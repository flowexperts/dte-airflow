import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Panel, PanelHead } from "./panel";

interface ErrorPanelProps {
  title?: string;
  message: ReactNode;
  detail?: string | null;
  /** Panel head label — defaults to "Error". */
  label?: string;
  className?: string;
}

/**
 * Full-width error panel. Message reads like product copy; the raw backend
 * string lives behind a "Show technical details" disclosure so power users
 * can still grab it without it being the first thing anyone sees.
 */
export function ErrorPanel({
  title,
  message,
  detail,
  label = "Error",
  className,
}: ErrorPanelProps) {
  return (
    <Panel className={className}>
      <PanelHead label={label} />
      <div className="p-4 text-[13px]">
        {title && <div className="font-medium text-red">{title}</div>}
        <div className={cn("text-muted", title ? "mt-1" : "")}>{message}</div>
        {detail && (
          <details className="mt-3 group">
            <summary className="cursor-pointer font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-text list-none">
              Show technical details
            </summary>
            <pre className="mt-2 font-mono text-[11.5px] text-subtle whitespace-pre-wrap break-words max-h-72 overflow-auto">
              {detail}
            </pre>
          </details>
        )}
      </div>
    </Panel>
  );
}

/**
 * Compact inline error for forms / list pages. Same disclosure pattern but
 * uses a bordered box that fits inline instead of a `Panel`.
 */
export function InlineError({
  title,
  message,
  detail,
  className,
}: {
  title?: string;
  message: ReactNode;
  detail?: string | null;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "border border-red/40 rounded-[var(--radius)] bg-code-bg p-3 text-[13px]",
        className,
      )}
    >
      {title && <div className="font-medium text-red">{title}</div>}
      <div className={cn("text-muted", title ? "mt-1" : "")}>{message}</div>
      {detail && (
        <details className="mt-2">
          <summary className="cursor-pointer font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle hover:text-text list-none">
            Show technical details
          </summary>
          <pre className="mt-2 font-mono text-[11px] text-subtle whitespace-pre-wrap break-words max-h-56 overflow-auto">
            {detail}
          </pre>
        </details>
      )}
    </div>
  );
}
