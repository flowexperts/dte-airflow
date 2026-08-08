"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";
import { Input } from "./form";
import { usePopoverPosition } from "./use-popover-position";
import {
  buildTree,
  collectLeaves,
  toDisplay,
  type FieldNode,
} from "./field-tree";

interface FieldOption {
  name: string;
  type?: string;
}

type Mode = "single" | "multi";

interface CommonProps {
  options: FieldOption[];
  placeholder?: string | undefined;
  className?: string | undefined;
  disabled?: boolean | undefined;
}

interface SingleProps extends CommonProps {
  mode: "single";
  value: string;
  onChange: (v: string) => void;
}

interface MultiProps extends CommonProps {
  mode: "multi";
  value: string[];
  onToggle: (wire: string) => void;
}

type Props = SingleProps | MultiProps;

interface VisibleRow {
  node: FieldNode;
  depth: number;
  isBranch: boolean;
}

function flatten(
  nodes: FieldNode[],
  expanded: Set<string>,
  depth = 0,
  out: VisibleRow[] = [],
): VisibleRow[] {
  for (const node of nodes) {
    const isBranch = !!node.children;
    out.push({ node, depth, isBranch });
    if (isBranch && expanded.has(node.wire)) {
      flatten(node.children!, expanded, depth + 1, out);
    }
  }
  return out;
}

function matches(node: FieldNode, q: string): boolean {
  if (!q) return true;
  if (node.name.toLowerCase().includes(q)) return true;
  if (node.wire.toLowerCase().includes(q)) return true;
  if (toDisplay(node.wire).toLowerCase().includes(q)) return true;
  if (node.children) return node.children.some((c) => matches(c, q));
  return false;
}

function filterTree(nodes: FieldNode[], q: string): FieldNode[] {
  if (!q) return nodes;
  const out: FieldNode[] = [];
  for (const n of nodes) {
    if (!matches(n, q)) continue;
    if (n.children) {
      const kids = filterTree(n.children, q);
      out.push({ ...n, children: kids });
    } else {
      out.push(n);
    }
  }
  return out;
}

function ancestorsOf(tree: FieldNode[], wire: string, acc: string[] = []): string[] | null {
  for (const n of tree) {
    if (n.wire === wire) return acc;
    if (n.children) {
      const hit = ancestorsOf(n.children, wire, [...acc, n.wire]);
      if (hit) return hit;
    }
  }
  return null;
}

export function FieldTreePicker(props: Props) {
  const { options, placeholder, className, disabled, mode } = props;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(0);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [mounted, setMounted] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => setMounted(true), []);

  const tree = useMemo(() => buildTree(options), [options]);
  const filtered = useMemo(
    () => filterTree(tree, query.trim().toLowerCase()),
    [tree, query],
  );

  // When searching, auto-expand every remaining branch so the hits show.
  const effectiveExpanded = useMemo(() => {
    if (!query.trim()) return expanded;
    const s = new Set<string>();
    const walk = (arr: FieldNode[]) => {
      for (const n of arr) {
        if (n.children) {
          s.add(n.wire);
          walk(n.children);
        }
      }
    };
    walk(filtered);
    return s;
  }, [filtered, query, expanded]);

  const rows = useMemo(
    () => flatten(filtered, effectiveExpanded),
    [filtered, effectiveExpanded],
  );

  /* Each nesting level costs 12px of indent (see the row's paddingLeft below)
   * on top of the chevron and checkbox, so a deep tree in a narrow trigger
   * leaves almost nothing for the label. Widen the popover by the depth it
   * actually has to render. */
  const maxDepth = useMemo(
    () => rows.reduce((m, r) => Math.max(m, r.depth), 0),
    [rows],
  );
  const pos = usePopoverPosition(inputRef, open, {
    minWidth: 220 + maxDepth * 12,
  });

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (
        containerRef.current?.contains(target) ||
        popoverRef.current?.contains(target)
      ) {
        return;
      }
      setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  useEffect(() => {
    if (highlight >= rows.length) setHighlight(0);
  }, [rows, highlight]);

  const toggleBranch = (wire: string) => {
    if (query.trim()) return; // search auto-expands
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(wire)) next.delete(wire);
      else next.add(wire);
      return next;
    });
  };

  const selectLeaf = (node: FieldNode) => {
    if (mode === "single") {
      (props as SingleProps).onChange(node.wire);
      setOpen(false);
      inputRef.current?.blur();
    } else {
      (props as MultiProps).onToggle(node.wire);
    }
  };

  const toggleBranchSelection = (branch: FieldNode) => {
    if (mode !== "multi") return;
    const leaves = collectLeaves([branch]).map((l) => l.wire);
    const selected = new Set((props as MultiProps).value);
    const allIn = leaves.every((w) => selected.has(w));
    for (const w of leaves) {
      const isSel = selected.has(w);
      if (allIn && isSel) (props as MultiProps).onToggle(w);
      else if (!allIn && !isSel) (props as MultiProps).onToggle(w);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open && (e.key === "ArrowDown" || e.key === "Enter")) {
      setOpen(true);
      return;
    }
    if (!open) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, rows.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "ArrowRight") {
      const row = rows[highlight];
      if (row?.isBranch && !effectiveExpanded.has(row.node.wire)) {
        e.preventDefault();
        toggleBranch(row.node.wire);
      }
    } else if (e.key === "ArrowLeft") {
      const row = rows[highlight];
      if (row?.isBranch && effectiveExpanded.has(row.node.wire)) {
        e.preventDefault();
        toggleBranch(row.node.wire);
      } else if (row) {
        // jump to parent
        const parents = ancestorsOf(filtered, row.node.wire) ?? [];
        const parentWire = parents[parents.length - 1];
        if (parentWire) {
          const idx = rows.findIndex((r) => r.node.wire === parentWire);
          if (idx >= 0) {
            e.preventDefault();
            setHighlight(idx);
          }
        }
      }
    } else if (e.key === "Enter") {
      const row = rows[highlight];
      if (!row) return;
      e.preventDefault();
      if (row.isBranch) {
        if (mode === "multi") toggleBranchSelection(row.node);
        else toggleBranch(row.node.wire);
      } else {
        selectLeaf(row.node);
      }
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  const selectedSet = useMemo(
    () => new Set(mode === "multi" ? (props as MultiProps).value : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mode, mode === "multi" ? (props as MultiProps).value : undefined],
  );

  const branchState = (branch: FieldNode): "none" | "all" | "partial" => {
    if (mode !== "multi") return "none";
    const leaves = collectLeaves([branch]).map((l) => l.wire);
    if (leaves.length === 0) return "none";
    const inSel = leaves.filter((w) => selectedSet.has(w)).length;
    if (inSel === 0) return "none";
    if (inSel === leaves.length) return "all";
    return "partial";
  };

  const inputValue = mode === "single"
    ? ((props as SingleProps).value
      ? toDisplay((props as SingleProps).value)
      : "")
    : query;

  return (
    <div ref={containerRef} className={cn("relative", className)}>
      <Input
        ref={inputRef}
        value={open ? query : inputValue}
        onChange={(e) => {
          setQuery(e.target.value);
          if (!open) setOpen(true);
        }}
        onFocus={() => {
          setOpen(true);
          setQuery("");
        }}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete="off"
      />
      {mounted && open && pos && rows.length > 0 &&
        createPortal(
          <div
            ref={popoverRef}
            style={pos.style}
            className="overflow-auto border border-border rounded-[var(--radius)] bg-surface shadow-lg py-0.5"
            role="listbox"
          >
            {rows.map((row, i) => {
              const { node, depth, isBranch } = row;
              const state = isBranch ? branchState(node) : "none";
              const isSelected = !isBranch && selectedSet.has(node.wire);
              const open = effectiveExpanded.has(node.wire);
              return (
                <button
                  key={node.wire}
                  type="button"
                  role="option"
                  aria-selected={i === highlight}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    setHighlight(i);
                    if (isBranch) {
                      if (mode === "multi") toggleBranchSelection(node);
                      else toggleBranch(node.wire);
                    } else {
                      selectLeaf(node);
                    }
                  }}
                  onMouseEnter={() => setHighlight(i)}
                  className={cn(
                    "w-full flex items-center gap-2 px-2 py-1 text-left font-mono text-[12.5px]",
                    i === highlight
                      ? "bg-[color:var(--accent-tint)] text-text"
                      : "text-text hover:bg-hover",
                  )}
                  style={{ paddingLeft: 8 + depth * 12 }}
                >
                  {isBranch ? (
                    <span
                      className="inline-block w-3 text-subtle select-none"
                      aria-hidden
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleBranch(node.wire);
                      }}
                    >
                      {open ? "▾" : "▸"}
                    </span>
                  ) : (
                    <span className="inline-block w-3" aria-hidden />
                  )}
                  {mode === "multi" && (
                    <span
                      className={cn(
                        "inline-flex items-center justify-center size-3.5 border rounded-sm text-[10px] leading-none",
                        (isBranch ? state === "all" : isSelected)
                          ? "border-accent bg-accent text-bg"
                          : state === "partial"
                            ? "border-accent text-accent"
                            : "border-border",
                      )}
                      aria-hidden
                    >
                      {isBranch
                        ? state === "all"
                          ? "✓"
                          : state === "partial"
                            ? "–"
                            : ""
                        : isSelected
                          ? "✓"
                          : ""}
                    </span>
                  )}
                  <span className={cn("flex-1 truncate", isBranch && "text-muted")}>
                    {node.name}
                  </span>
                  {!isBranch && node.type && (
                    <span className="text-subtle text-[11px]">{node.type}</span>
                  )}
                  {isBranch && node.children && (
                    <span className="text-subtle text-[10.5px]">
                      {node.children.length}
                    </span>
                  )}
                </button>
              );
            })}
          </div>,
          document.body,
        )}
      {mounted && open && pos && rows.length === 0 &&
        createPortal(
          <div
            ref={popoverRef}
            style={pos.style}
            className="border border-border rounded-[var(--radius)] bg-surface shadow-lg px-2.5 py-2 text-[12px] text-subtle"
          >
            {options.length === 0
              ? "Infer schema on the source to see fields."
              : "No matches."}
          </div>,
          document.body,
        )}
    </div>
  );
}
