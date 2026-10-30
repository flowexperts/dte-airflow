import { cn } from "@/lib/cn";
import { useEffect, useRef, type ReactNode, type CSSProperties } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  width?: string;
  align?: "left" | "right" | "center";
  render: (row: T, i: number) => ReactNode;
}

export interface DataTableSelection<T> {
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: () => void;
  rowId: (row: T) => string;
}

const SELECT_COL_WIDTH = "32px";

function HeaderCheckbox({
  checked,
  indeterminate,
  onChange,
}: {
  checked: boolean;
  indeterminate: boolean;
  onChange: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate && !checked;
  }, [indeterminate, checked]);
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      onChange={onChange}
      className="h-3.5 w-3.5 cursor-pointer accent-accent"
      aria-label="Select all rows"
    />
  );
}

export function DataTable<T>({
  columns,
  rows,
  onRowClick,
  emptyText = "No rows.",
  className,
  selection,
}: {
  columns: Column<T>[];
  rows: T[];
  onRowClick?: ((row: T, i: number) => void) | undefined;
  emptyText?: string | undefined;
  className?: string | undefined;
  selection?: DataTableSelection<T> | undefined;
}) {
  const widths = selection
    ? [SELECT_COL_WIDTH, ...columns.map((c) => c.width ?? "1fr")]
    : columns.map((c) => c.width ?? "1fr");
  const gridStyle: CSSProperties = { gridTemplateColumns: widths.join(" ") };

  const allIds = selection ? rows.map(selection.rowId) : [];
  const selectedCount = selection ? allIds.filter((id) => selection.selectedIds.has(id)).length : 0;
  const allSelected = selection ? selectedCount > 0 && selectedCount === rows.length : false;
  const someSelected = selection ? selectedCount > 0 : false;

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
        {selection && (
          <div className="flex items-center">
            <HeaderCheckbox
              checked={allSelected}
              indeterminate={someSelected}
              onChange={selection.onToggleAll}
            />
          </div>
        )}
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
        <div className="px-3.5 py-6 text-sm text-subtle text-center">{emptyText}</div>
      ) : (
        rows.map((row, i) => {
          const id = selection ? selection.rowId(row) : undefined;
          const isSelected = selection && id ? selection.selectedIds.has(id) : false;
          return (
            <div
              key={i}
              onClick={onRowClick ? () => onRowClick(row, i) : undefined}
              className={cn(
                "grid gap-0 px-3.5 h-[52px] items-center border-b border-border text-sm last:border-b-0 transition-colors",
                onRowClick && "cursor-pointer hover:bg-hover",
                isSelected && "bg-hover",
              )}
              style={gridStyle}
            >
              {selection && id !== undefined && (
                <div className="flex items-center" onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => selection.onToggle(id)}
                    className="h-3.5 w-3.5 cursor-pointer accent-accent"
                    aria-label={`Select row ${id}`}
                  />
                </div>
              )}
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
          );
        })
      )}
    </div>
  );
}
