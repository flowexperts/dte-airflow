"use client";

/** Table cell renderer for arbitrary JSON values.
 *  - null / undefined → dim "null"
 *  - primitives       → text (truncated to cell width)
 *  - objects / arrays → collapsed one-line preview; click to expand pretty JSON
 *
 *  Uses native <details> so no state or event wiring is needed and rows
 *  can be re-rendered freely without losing expand state within the row.
 */
export function JsonCell({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return <span className="text-subtle">null</span>;
  }
  if (typeof value !== "object") {
    const s = String(value);
    return (
      <span className="truncate block max-w-[280px]" title={s}>
        {s}
      </span>
    );
  }
  const pretty = JSON.stringify(value, null, 2);
  const oneLine = JSON.stringify(value);
  return (
    <details className="group max-w-[280px]">
      <summary className="cursor-pointer list-none flex items-center gap-1.5 truncate">
        <span className="text-subtle text-[10px] transition-transform group-open:rotate-90">
          ▶
        </span>
        <span className="text-accent truncate" title={oneLine}>
          {oneLine}
        </span>
      </summary>
      <pre className="mt-1.5 p-2 rounded bg-code-bg text-text text-[11.5px] leading-snug whitespace-pre-wrap break-all max-w-none">
        {pretty}
      </pre>
    </details>
  );
}
