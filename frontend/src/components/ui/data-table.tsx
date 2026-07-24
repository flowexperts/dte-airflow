"use client";

import { cn } from "@/lib/cn";
import type { ReactNode, CSSProperties } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  width?: string;
  align?: "left" | "right" | "center";
  render: (row: T, i: number) => ReactNode;
}

export function DataTable<T>({
  columns,
  rows,
  onRowClick,
  emptyText = "No rows.",
  className,
}: {
  columns: Column<T>[];
  rows: T[];
  onRowClick?: ((row: T, i: number) => void) | undefined;
  emptyText?: string | undefined;
  className?: string | undefined;
}) {
  const gridTemplate = columns.map((c) => c.width ?? "1fr").join(" ");
  const gridStyle: CSSProperties = { gridTemplateColumns: gridTemplate };

  return (
    <div
      className={cn(
        "border border-border rounded-[var(--radius)] bg-surface overflow-hidden",
        className,
      )}
    >
      <div
        className="grid gap-0 px-3.5 h-[34px] items-center bg-surface-2 border-b border-border font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle"
        style={gridStyle}
      >
        {columns.map((c) => (
          <div
            key={c.key}
            className={cn(
              c.align === "right" && "text-right",
              c.align === "center" && "text-center",
            )}
          >
            {c.header}
          </div>
        ))}
      </div>
      {rows.length === 0 ? (
        <div className="px-3.5 py-6 text-sm text-subtle text-center">
          {emptyText}
        </div>
      ) : (
        rows.map((row, i) => (
          <div
            key={i}
            onClick={onRowClick ? () => onRowClick(row, i) : undefined}
            className={cn(
              "grid gap-0 px-3.5 h-[52px] items-center border-b border-border text-sm last:border-b-0 transition-colors",
              onRowClick && "cursor-pointer hover:bg-hover",
            )}
            style={gridStyle}
          >
            {columns.map((c) => (
              <div
                key={c.key}
                className={cn(
                  "min-w-0",
                  c.align === "right" && "text-right",
                  c.align === "center" && "text-center",
                )}
              >
                {c.render(row, i)}
              </div>
            ))}
          </div>
        ))
      )}
    </div>
  );
}
