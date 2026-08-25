"use client";

import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Dropdown,
  Field,
  FieldPicker,
  FieldMultiSelect,
  Input,
  Segmented,
  Textarea,
  type DropdownOption,
} from "@/components/ui";
import { usePopoverPosition } from "@/components/ui/use-popover-position";
import { useStepFields, useJoinOperands } from "../schema-context";
import type { SchemaField } from "@/lib/api";
import { usePipelineParams } from "../params-context";
import { toDisplay } from "@/components/ui";
import { cn } from "@/lib/cn";
import type { StepShape, GroupByEntry, DatePart, DataModelField } from "./types";
import { LookupTablePicker } from "../LookupTablePicker";
import { SYSTEM_VARS, type SystemVar } from "@/lib/system-vars";

/** Compact λ-labelled dropdown that writes a `{{sysvar}}` sentinel into a
 *  filter value cell. Rendered alongside date/timestamp inputs where the
 *  native picker can't hold a sentinel string. */
/** Icon-sized dynamic-value menu. Absolutely-positioned so it can overlay
 *  the right edge of a native date/datetime input, next to the browser's
 *  calendar picker icon. Popover portals to <body> to escape any
 *  overflow-hidden ancestor. */
function DynamicValueMenu({
  vars,
  onPick,
  widthRef,
}: {
  vars: readonly SystemVar[];
  onPick: (token: string) => void;
  /** Element whose width the popover should match — typically the input
   *  wrapper. Falls back to the trigger's width if the ref is empty. */
  widthRef?: React.RefObject<HTMLElement | null>;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);

  /* Anchor to the input wrapper when we have one — the trigger is a 20px
   * glyph sitting inside it, so anchoring to the trigger would give a 20px
   * popover. usePopoverPosition handles the flip and viewport clamp. */
  const pos = usePopoverPosition(
    (widthRef ?? triggerRef) as React.RefObject<HTMLElement | null>,
    open,
  );

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (triggerRef.current?.contains(t) || popRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        aria-label="Dynamic value"
        title="Dynamic value"
        className="h-5 w-5 flex items-center justify-center rounded text-[13px] font-mono text-subtle hover:text-accent hover:bg-[color:var(--accent-tint)] transition-colors"
      >
        λ
      </button>
      {open && pos &&
        createPortal(
          <div
            ref={popRef}
            style={pos.style}
            className="overflow-auto border border-border rounded-[var(--radius)] bg-surface shadow-lg py-1"
            role="listbox"
          >
            {vars.map((v) => (
              <button
                key={v}
                type="button"
                role="option"
                onMouseDown={(e) => {
                  e.preventDefault();
                  onPick(`{{${v}}}`);
                  setOpen(false);
                }}
                className="w-full flex items-center justify-between gap-3 px-2.5 py-1.5 text-left text-[13px] text-text hover:bg-[color:var(--accent-tint)]"
              >
                <span className="font-mono truncate">{`{{${v}}}`}</span>
                <span className="font-mono text-[11px] text-subtle shrink-0">
                  dynamic
                </span>
              </button>
            ))}
          </div>,
          document.body,
        )}
    </>
  );
}

/** Filter value cell wrapping <Input> + λ dynamic-value menu + a
 *  calendar-reset button that appears when the value is a `{{sentinel}}`.
 *  Consolidates the three overlay sites in the Basic filter row. */
function DateValueField({
  value,
  onChange,
  baseType,
  dynVars,
  placeholder,
  disabled,
  list,
}: {
  value: string;
  onChange: (next: string) => void;
  /** Native input type when the value is *not* a sentinel. */
  baseType: "text" | "date" | "datetime-local";
  dynVars: readonly SystemVar[];
  placeholder?: string;
  disabled?: boolean;
  list?: string;
}) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const isSentinel = /^\{\{[\w.]+\}\}$/.test(value);
  const effectiveType = isSentinel ? "text" : baseType;
  const isDatey = baseType === "date" || baseType === "datetime-local";
  // Reserve room on the right for the overlays. When a sentinel is set the
  // native calendar is gone, so we render our own — needs its own slot too.
  const padRight =
    dynVars.length === 0
      ? undefined
      : isSentinel
        ? "pr-14"
        : isDatey
          ? "pr-14"
          : "pr-7";
  return (
    <div ref={wrapperRef} className="relative min-w-0">
      <Input
        type={effectiveType}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        list={list}
        disabled={disabled}
        className={cn("min-w-0 w-full", padRight)}
      />
      {dynVars.length > 0 && (
        <div
          className={cn(
            "absolute top-1/2 -translate-y-1/2 flex items-center gap-1",
            // When a sentinel is showing, we're in text mode and can hug
            // the right edge. Otherwise leave room for the browser icon.
            isSentinel ? "right-1.5" : isDatey ? "right-7" : "right-1.5",
          )}
        >
          {isSentinel && <CalendarResetButton onClear={() => onChange("")} />}
          <DynamicValueMenu
            vars={dynVars}
            onPick={onChange}
            widthRef={wrapperRef}
          />
        </div>
      )}
    </div>
  );
}

/** Small calendar-shaped button rendered when the field holds a `{{sentinel}}`
 *  (native date input can't display it, so the browser's calendar icon is
 *  gone). Clicking clears the value, which lets the input flip back to
 *  date/datetime-local and the browser's own picker reappears. */
function CalendarResetButton({ onClear }: { onClear: () => void }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClear();
      }}
      aria-label="Back to date picker"
      title="Back to date picker"
      className="h-5 w-5 flex items-center justify-center rounded text-subtle hover:text-accent hover:bg-[color:var(--accent-tint)] transition-colors"
    >
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden>
        <rect x="2" y="3" width="12" height="11" rx="1.5"
          fill="none" stroke="currentColor" strokeWidth="1.3" />
        <path d="M2 6h12M5 2v3M11 2v3"
          fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      </svg>
    </button>
  );
}

type Setter = (patch: Partial<StepShape>) => void;

/* --------------- Variable picker (trigger-time params + system vars) --------------- */

function VariablePickerHint({ onInsert }: { onInsert: (token: string) => void }) {
  const declared = usePipelineParams();
  return (
    <div className="mt-2 space-y-2 rounded border border-border bg-code-bg px-2.5 py-2">
      <div>
        <div className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle mb-1">
          System
        </div>
        <div className="flex flex-wrap gap-1.5">
          {SYSTEM_VARS.map((v) => {
            const token = `{{${v}}}`;
            return (
              <button
                key={v}
                type="button"
                onClick={() => onInsert(token)}
                className="font-mono text-[11px] text-accent hover:text-accent-h bg-surface border border-border rounded px-1.5 py-0.5"
              >
                {token}
              </button>
            );
          })}
        </div>
      </div>
      <div>
        <div className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle mb-1">
          Inputs
        </div>
        {declared.length === 0 ? (
          <div className="font-mono text-[10.5px] text-subtle">
            No inputs declared. Add them in the Inputs panel.
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {declared.map((p) => (
              <button
                key={p.name}
                type="button"
                onClick={() => onInsert(`{{params.${p.name}}}`)}
                title={p.description ?? ""}
                className="font-mono text-[11px] text-gold hover:brightness-125 bg-surface border border-border rounded px-1.5 py-0.5"
              >
                {`{{params.${p.name}}}`}
                <span className="ml-1 text-subtle">· {p.type}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="font-mono text-[10.5px] text-subtle">
        Resolved at run time. Values substitute as strings — cast in SQL where needed
        (<span className="font-mono">{"'{{params.d}}'::date"}</span>).
      </div>
    </div>
  );
}

/* --------------- Filter — Basic + Advanced tabs --------------- */

type FilterOp =
  | "="
  | "!="
  | ">"
  | "<"
  | ">="
  | "<="
  | "LIKE"
  | "IN"
  | "IS NULL"
  | "IS NOT NULL"
  | "BETWEEN";

interface FilterRule {
  field: string;
  op: FilterOp;
  value: string;
  join: "AND" | "OR";
}

const FILTER_OPS: FilterOp[] = [
  "=", "!=", ">", "<", ">=", "<=", "LIKE", "IN", "IS NULL", "IS NOT NULL", "BETWEEN",
];

const OPS_WITHOUT_VALUE = new Set<FilterOp>(["IS NULL", "IS NOT NULL"]);

/** DuckDB identifier quote — wraps in "" and escapes internal " as "".
 *  Dots navigate STRUCT members, so each dot-separated segment is quoted
 *  individually: `order.amount` → `"order"."amount"`.  A single quoted
 *  `"order.amount"` would ask DuckDB for a top-level column literally
 *  named `order.amount`, which is not what struct paths mean. */
function quoteIdent(name: string): string {
  return name
    .split(".")
    .map((seg) => `"${seg.replace(/"/g, '""')}"`)
    .join(".");
}

/** DuckDB string literal quote — wraps in '' and escapes internal ' as ''. */
function quoteString(value: string): string {
  return `'${value.replace(/'/g, "''")}'`;
}

/**
 * Turn a value into a safe SQL literal.
 * Bare numbers (int or float) pass through as-is; everything else is quoted as string.
 * Never concatenates raw user input into the SQL string without going through here.
 */
function safeLiteral(v: string): string {
  const trimmed = v.trim();
  if (trimmed === "") return "''";
  // {{params.X}} / {{today}} placeholders: quote so the resolved value
  // (ISO date/timestamp string) lands as a valid SQL literal. DuckDB
  // implicitly casts against the column type. Numeric comparisons still
  // work because DuckDB coerces string → number.
  if (/^\{\{[\w.]+\}\}$/.test(trimmed)) return `'${trimmed}'`;
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) return trimmed;
  if (/^(true|false)$/i.test(trimmed)) return trimmed.toUpperCase();
  return quoteString(trimmed);
}

/** Inverse of safeLiteral for display in an input: unwrap a quoted string
 *  literal, leave bare numbers/booleans as typed. */
function displayLiteral(v: string): string {
  const t = v.trim();
  if (t.startsWith("'") && t.endsWith("'") && t.length >= 2)
    return t.slice(1, -1).replace(/''/g, "'");
  return t;
}

/** Map a schema-reported column type (ibis/DuckDB) to a native <input>
 *  type so date/timestamp filter cells get a picker. Types we don't
 *  recognise fall back to "text" — safe for numerics + strings, which the
 *  server coerces anyway. */
function fieldInputType(colType: string | undefined): "text" | "date" | "datetime-local" {
  if (!colType) return "text";
  const t = colType.toLowerCase();
  if (t.startsWith("date") && !t.startsWith("datetime")) return "date";
  if (t.startsWith("timestamp") || t.startsWith("datetime")) return "datetime-local";
  return "text";
}

function ruleToSql(r: FilterRule): string {
  if (!r.field) return "";
  const f = quoteIdent(r.field);
  switch (r.op) {
    case "IS NULL":
    case "IS NOT NULL":
      return `${f} ${r.op}`;
    case "IN": {
      const parts = r.value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .map(safeLiteral);
      if (parts.length === 0) return "";
      return `${f} IN (${parts.join(", ")})`;
    }
    case "BETWEEN": {
      const parts = r.value.split(",").map((s) => s.trim()).filter(Boolean);
      const [lo, hi] = parts;
      if (parts.length !== 2 || lo === undefined || hi === undefined) return "";
      return `${f} BETWEEN ${safeLiteral(lo)} AND ${safeLiteral(hi)}`;
    }
    case "LIKE":
      return `${f} LIKE ${safeLiteral(r.value)}`;
    default:
      return `${f} ${r.op} ${safeLiteral(r.value)}`;
  }
}

function rulesToSql(rules: FilterRule[]): string {
  const parts: string[] = [];
  rules.forEach((r) => {
    const sql = ruleToSql(r);
    if (!sql) return;
    if (parts.length === 0) parts.push(sql);
    else parts.push(`${r.join} ${sql}`);
  });
  return parts.join(" ");
}

/**
 * Attempt to parse a simple SQL WHERE clause (as produced by rulesToSql) back
 * into a FilterRule list. Handles AND-combined (or OR-combined) predicates of
 * the forms:
 *   "col" = 'value'       "col" > 5          "col" IS NULL
 *   "col" IN (a, b, c)    "col" BETWEEN x AND y
 *   "col" LIKE 'pat%'
 *
 * Returns null if the SQL is too complex to round-trip cleanly — callers
 * should leave Basic empty and keep the raw Advanced text intact.
 */
function tryParseBasicSql(sql: string): FilterRule[] | null {
  const trimmed = sql.trim();
  if (!trimmed) return [];

  // Unquote a DuckDB string literal: 'val' → val, '' inside → '
  function unquoteString(s: string): string {
    return s.slice(1, -1).replace(/''/g, "'");
  }

  // Parse a dot-chained identifier — each segment may be quoted ("a") or
  // bare (a). Handles legacy pre-quoted-ident filter SQL like `col = 5`.
  // Returns [fieldName, remainingStr] or null.
  function parseIdent(s: string): [string, string] | null {
    const parts: string[] = [];
    let rest = s.trimStart();
    while (true) {
      if (rest.startsWith('"')) {
        let i = 1;
        while (i < rest.length) {
          if (rest[i] === '"') {
            if (rest[i + 1] === '"') { i += 2; continue; }
            break;
          }
          i++;
        }
        if (rest[i] !== '"') return null; // unclosed quote
        parts.push(rest.slice(1, i).replace(/""/g, '"'));
        rest = rest.slice(i + 1);
      } else {
        const bare = rest.match(/^([A-Za-z_][\w$]*)([\s\S]*)/);
        if (!bare) break;
        parts.push(bare[1]!);
        rest = bare[2]!;
      }
      if (rest.startsWith(".")) { rest = rest.slice(1); continue; }
      break;
    }
    if (parts.length === 0) return null;
    return [parts.join("."), rest.trimStart()];
  }

  // Parse a single value literal (number, boolean, 'string', {{sentinel}}).
  // Returns [displayValue, remainingStr] or null.
  function parseLiteral(s: string): [string, string] | null {
    const rest = s.trimStart();
    // '{{sentinel}}' quoted (current emit form) — unwrap to display form.
    const quotedSentinelMatch = rest.match(/^'(\{\{\s*[\w.]+\s*\}\})'([\s\S]*)/);
    if (quotedSentinelMatch)
      return [quotedSentinelMatch[1]!, quotedSentinelMatch[2]!.trimStart()];
    // {{sentinel}} unquoted — legacy form; still parse so old pipelines
    // round-trip cleanly on next save.
    const sentinelMatch = rest.match(/^(\{\{\s*[\w.]+\s*\}\})([\s\S]*)/);
    if (sentinelMatch) return [sentinelMatch[1]!, sentinelMatch[2]!.trimStart()];
    if (rest.startsWith("'")) {
      // Find matching close quote ('' is an escaped single quote)
      let i = 1;
      while (i < rest.length) {
        if (rest[i] === "'") {
          if (rest[i + 1] === "'") { i += 2; continue; }
          break;
        }
        i++;
      }
      if (rest[i] !== "'") return null; // unclosed
      return [unquoteString(rest.slice(0, i + 1)), rest.slice(i + 1).trimStart()];
    }
    // Unquoted number
    const numMatch = rest.match(/^(-?\d+(?:\.\d+)?)([\s\S]*)/);
    if (numMatch) return [numMatch[1]!, numMatch[2]!.trimStart()];
    // Unquoted boolean (TRUE/FALSE as emitted by safeLiteral)
    const boolMatch = rest.match(/^(TRUE|FALSE)([\s\S]*)/i);
    if (boolMatch) return [boolMatch[1]!.toLowerCase(), boolMatch[2]!.trimStart()];
    return null;
  }

  // Parse one predicate starting from `s`.
  // Returns [partialRule, remainingStr] or null.
  function parsePredicate(s: string): [Omit<FilterRule, "join">, string] | null {
    const identResult = parseIdent(s);
    if (!identResult) return null;
    const [field, afterIdent] = identResult;

    // IS NULL / IS NOT NULL
    const isNullMatch = afterIdent.match(/^IS\s+(NOT\s+)?NULL([\s\S]*)/i);
    if (isNullMatch) {
      const op: FilterOp = isNullMatch[1] ? "IS NOT NULL" : "IS NULL";
      return [{ field, op, value: "" }, isNullMatch[2]!.trimStart()];
    }

    // LIKE
    const likeMatch = afterIdent.match(/^LIKE\s+([\s\S]*)/i);
    if (likeMatch) {
      const litResult = parseLiteral(likeMatch[1]!);
      if (!litResult) return null;
      const [value, rest] = litResult;
      return [{ field, op: "LIKE", value }, rest];
    }

    // IN (...)
    const inMatch = afterIdent.match(/^IN\s*\(([\s\S]*)/i);
    if (inMatch) {
      let inside = inMatch[1]!;
      const items: string[] = [];
      while (true) {
        inside = inside.trimStart();
        if (inside.startsWith(")")) { inside = inside.slice(1).trimStart(); break; }
        if (items.length > 0) {
          if (!inside.startsWith(",")) return null;
          inside = inside.slice(1).trimStart();
        }
        const litResult = parseLiteral(inside);
        if (!litResult) return null;
        items.push(litResult[0]!);
        inside = litResult[1]!;
      }
      return [{ field, op: "IN", value: items.join(", ") }, inside];
    }

    // BETWEEN x AND y
    const betweenMatch = afterIdent.match(/^BETWEEN\s+([\s\S]*)/i);
    if (betweenMatch) {
      const lo = parseLiteral(betweenMatch[1]!);
      if (!lo) return null;
      const andMatch = lo[1].match(/^AND\s+([\s\S]*)/i);
      if (!andMatch) return null;
      const hi = parseLiteral(andMatch[1]!);
      if (!hi) return null;
      return [{ field, op: "BETWEEN", value: `${lo[0]}, ${hi[0]}` }, hi[1]];
    }

    // Comparison operators (!=, >=, <=, >, <, =)
    const compMatch = afterIdent.match(/^(!=|>=|<=|>|<|=)\s*([\s\S]*)/);
    if (compMatch) {
      const op = compMatch[1] as FilterOp;
      const litResult = parseLiteral(compMatch[2]!);
      if (!litResult) return null;
      const [value, rest] = litResult;
      return [{ field, op, value }, rest];
    }

    return null;
  }

  const rules: FilterRule[] = [];
  let remaining = trimmed;
  let isFirst = true;

  while (remaining.length > 0) {
    let join: "AND" | "OR" = "AND";

    if (!isFirst) {
      const joinMatch = remaining.match(/^(AND|OR)\s+([\s\S]*)/i);
      if (!joinMatch) return null; // unexpected token — SQL is too complex
      join = joinMatch[1]!.toUpperCase() as "AND" | "OR";
      remaining = joinMatch[2]!;
    }

    const predResult = parsePredicate(remaining);
    if (!predResult) return null;
    const [pred, rest] = predResult;
    rules.push({ ...pred, join });
    remaining = rest.trimStart();
    isFirst = false;
  }

  return rules.length > 0 ? rules : null;
}

/**
 * The structured, injection-safe condition builder: field picker + operator +
 * value, AND/OR-joined, emitting SQL through quoteIdent/safeLiteral only.
 *
 * Extracted from FilterEditor so the `case` step's branches build their
 * conditions with the identical UI — two implementations of "compose a
 * predicate" would drift, and the drift is a quoting bug.
 */
function ConditionRules({
  rules,
  onChange,
}: {
  rules: FilterRule[];
  onChange: (next: FilterRule[]) => void;
}) {
  const allFields = useStepFields();
  const declaredParams = usePipelineParams();
  // Native <datalist> id — one per instance is fine since we suggest the same
  // declared inputs to every value cell.
  const paramsListId = `filter-params-${useId()}`;

  const addRule = () =>
    onChange([...rules, { field: "", op: "=", value: "", join: "AND" }]);
  const updateRule = (i: number, patch: Partial<FilterRule>) =>
    onChange(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const removeRule = (i: number) => onChange(rules.filter((_, j) => j !== i));
  const previewExpr = rulesToSql(rules);

  return (
      <div className="space-y-1.5">
        {rules.length === 0 && (
          <div className="font-mono text-[11.5px] text-subtle">
            No conditions. Add one below.
          </div>
        )}
        {rules.map((r, i) => {
          const noValue = OPS_WITHOUT_VALUE.has(r.op);
          // Look up the selected field's declared type so date/timestamp
          // columns get a native picker instead of a plain text input.
          const fieldMeta = allFields.find((f) => f.name === r.field);
          const inputType = fieldInputType(fieldMeta?.type);
          // Native date/datetime pickers can't hold a {{sentinel}}, so we
          // surface a compact λ dropdown beside them. Filter the sysvars
          // to the shapes that will coerce cleanly.
          const dynVars =
            inputType === "date"
              ? SYSTEM_VARS.filter((v) => v !== "now")
              : inputType === "datetime-local"
                ? SYSTEM_VARS
                : [];
          return (
            <div
              key={i}
              className="flex flex-wrap items-center gap-2"
            >
              {i === 0 ? (
                <span className="w-[60px] shrink-0 font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle text-center">
                  where
                </span>
              ) : (
                <select
                  value={r.join}
                  onChange={(e) => updateRule(i, { join: e.target.value as "AND" | "OR" })}
                  className="w-[60px] shrink-0 bg-bg border border-border rounded px-2 py-1.5 text-[12.5px] focus:outline-none focus:border-accent"
                >
                  <option value="AND">AND</option>
                  <option value="OR">OR</option>
                </select>
              )}
              <FieldPicker
                value={r.field}
                onChange={(v) => updateRule(i, { field: v })}
                options={allFields}
                placeholder="field"
                variant="tree"
                className="basis-[190px] grow"
              />
              <select
                value={r.op}
                onChange={(e) => updateRule(i, { op: e.target.value as FilterOp })}
                className="w-[120px] shrink-0 bg-bg border border-border rounded px-2 py-1.5 text-[12.5px] font-mono focus:outline-none focus:border-accent"
              >
                {FILTER_OPS.map((op) => (
                  <option key={op} value={op}>
                    {op}
                  </option>
                ))}
              </select>
              <div className="basis-[210px] grow min-w-0">
              {r.op === "BETWEEN" ? (
                (() => {
                  const [lo = "", hi = ""] = (r.value ?? "")
                    .split(",")
                    .map((s) => s.trim());
                  const commit = (nlo: string, nhi: string) => {
                    const parts = [nlo.trim(), nhi.trim()];
                    updateRule(i, {
                      value: parts.every((s) => s === "") ? "" : parts.join(", "),
                    });
                  };
                  return (
                    <div className="flex flex-wrap items-center gap-1">
                      <DateValueField
                        value={lo}
                        onChange={(v) => commit(v, hi)}
                        baseType={inputType}
                        dynVars={dynVars}
                        placeholder="min"
                        list={paramsListId}
                      />
                      <span className="w-4 shrink-0 text-center font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle">
                        and
                      </span>
                      <DateValueField
                        value={hi}
                        onChange={(v) => commit(lo, v)}
                        baseType={inputType}
                        dynVars={dynVars}
                        placeholder="max"
                        list={paramsListId}
                      />
                    </div>
                  );
                })()
              ) : (
                (() => {
                  // IN / LIKE keep text semantics; disable pickers there.
                  const suppressed = r.op === "IN" || r.op === "LIKE" || noValue;
                  return (
                    <DateValueField
                      value={r.value}
                      onChange={(v) => updateRule(i, { value: v })}
                      baseType={suppressed ? "text" : inputType}
                      dynVars={suppressed ? [] : dynVars}
                      placeholder={r.op === "IN" ? "a, b, c" : "value"}
                      disabled={noValue}
                      list={paramsListId}
                    />
                  );
                })()
              )}
              </div>
              <button
                type="button"
                onClick={() => removeRule(i)}
                className="w-[28px] shrink-0 text-subtle hover:text-red text-sm"
                aria-label="Remove condition"
              >
                ×
              </button>
            </div>
          );
        })}
        <button
          type="button"
          onClick={addRule}
          className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
        >
          + Add condition
        </button>
        {previewExpr && (
          <div className="mt-2">
            <div className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle mb-1">
              Generated SQL
            </div>
            <code className="block font-mono text-[12px] text-muted bg-code-bg border border-border rounded px-2.5 py-1.5 whitespace-pre-wrap break-words">
              {previewExpr}
            </code>
          </div>
        )}
        <datalist id={paramsListId}>
          {declaredParams.map((p) => (
            <option
              key={`p-${p.name}`}
              value={`{{params.${p.name}}}`}
              label={`${p.name} · ${p.type}`}
            />
          ))}
          {SYSTEM_VARS.map((v) => (
            <option
              key={`s-${v}`}
              value={`{{${v}}}`}
              label={`${v} · dynamic`}
            />
          ))}
        </datalist>
      </div>
  );
}

export function FilterEditor({ step, set }: { step: StepShape; set: Setter }) {
  // Mode is local UI state — not persisted on the step. Prefer Basic: it is
  // the structured, injection-safe editor and where most conditions belong.
  // We open in Advanced only when the saved SQL can't be represented as
  // rules, because an empty Basic tab would read as "the filter is gone".
  const parsedOnMount = useRef<FilterRule[] | null>(
    step.expr ? tryParseBasicSql(step.expr as string) : [],
  );
  const [mode, setMode] = useState<"basic" | "advanced">(
    parsedOnMount.current === null ? "advanced" : "basic",
  );

  // Each tab keeps its own independent local state so switching tabs never
  // destroys content the user typed on the other tab.
  //
  // `rules`        — source of truth for the Basic tab.
  // `advancedText` — source of truth for the Advanced tab.
  //
  // On first mount we try to pre-populate Basic by parsing the existing expr
  // so a round-trippable expression shows up immediately in Basic mode.
  const [rules, setRules] = useState<FilterRule[]>(
    () => parsedOnMount.current ?? [],
  );
  const [advancedText, setAdvancedText] = useState<string>(
    (step.expr as string) ?? "",
  );

  const commitRules = (next: FilterRule[]) => {
    setRules(next);
    // Only push the generated SQL to parent when Basic tab is active — the
    // Advanced tab owns the wire value while it is displayed.
    if (mode === "basic") set({ expr: rulesToSql(next) });
  };

  const handleAdvancedChange = (text: string) => {
    setAdvancedText(text);
    set({ expr: text });
  };

  const switchToBasic = () => {
    // Try to parse the current Advanced SQL into structured rules.
    const parsed = tryParseBasicSql(advancedText);
    if (parsed !== null) {
      // Successfully round-tripped — populate Basic and keep expr in sync.
      setRules(parsed);
      set({ expr: rulesToSql(parsed) });
    }
    // If too complex: leave Basic empty (`rules` stays as-is from previous
    // Basic session or []) and keep `advancedText` intact so the user can
    // switch back to Advanced without losing their SQL.
    setMode("basic");
  };

  const switchToAdvanced = () => {
    // If the user has never typed in Advanced yet, pre-populate it with
    // whatever Basic currently generates, so they have a starting point.
    if (advancedText === "") {
      const basicSql = rulesToSql(rules);
      if (basicSql) {
        setAdvancedText(basicSql);
        set({ expr: basicSql });
      }
    }
    // Otherwise: Advanced already has content (user typed there before) —
    // leave it exactly as-is.
    setMode("advanced");
  };

  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between">
        <div className="inline-flex border border-border rounded-[var(--radius)] bg-surface p-0.5">
          {(["basic", "advanced"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => {
                if (m === "basic" && mode === "advanced") switchToBasic();
                else if (m === "advanced" && mode === "basic") switchToAdvanced();
              }}
              className={cn(
                "px-3 py-1 text-[12.5px] font-medium rounded-[3px] transition-colors capitalize",
                m === mode
                  ? "bg-[color:var(--accent-tint)] text-accent"
                  : "text-muted hover:text-text",
              )}
            >
              {m}
            </button>
          ))}
        </div>
        <span className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle">
          {mode === "basic" ? "structured · safe" : "raw sql"}
        </span>
      </div>

      {mode === "basic" ? (
        <ConditionRules rules={rules} onChange={commitRules} />
      ) : (
        <Field
          label="Expression"
          hint="raw DuckDB WHERE clause. You are responsible for quoting — for safe, structured input use Basic."
        >
          <Textarea
            value={advancedText}
            onChange={(e) => handleAdvancedChange(e.target.value)}
            placeholder="amount > 0 AND status = 'completed'"
          />
          <VariablePickerHint
            onInsert={(token) => handleAdvancedChange(advancedText + token)}
          />
        </Field>
      )}
    </div>
  );
}

/**
 * We keep an internal ordered list of {from, to} rows so the user can add
 * blank rows and edit incrementally. The parent step stores `mappings` as
 * a plain object; we sync in one direction from the local list.
 */
export function RenameEditor({ step, set }: { step: StepShape; set: Setter }) {
  const allFields = useStepFields();
  const mappings = (step.mappings as Record<string, string>) ?? {};

  const initial = () =>
    Object.entries(mappings).map(([from, to]) => ({ from, to }));

  const [rows, setRows] = useState<{ from: string; to: string }[]>(initial);

  // Re-sync if an external mapping (e.g. loading an existing pipeline) diverges.
  useEffect(() => {
    const asObj: Record<string, string> = {};
    for (const r of rows) if (r.from && r.to) asObj[r.from] = r.to;
    const same =
      Object.keys(asObj).length === Object.keys(mappings).length &&
      Object.entries(asObj).every(([k, v]) => mappings[k] === v);
    if (!same) setRows(initial());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mappings]);

  const commit = (next: { from: string; to: string }[]) => {
    setRows(next);
    const obj: Record<string, string> = {};
    for (const r of next) if (r.from && r.to) obj[r.from] = r.to;
    set({ mappings: obj });
  };

  const updateRow = (i: number, patch: Partial<{ from: string; to: string }>) =>
    commit(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const removeRow = (i: number) => commit(rows.filter((_, j) => j !== i));

  const addRow = () => commit([...rows, { from: "", to: "" }]);

  const usedFromNames = new Set(rows.map((r) => r.from));

  return (
    <Field label="Mappings" hint="rename fields — old name on the left, new on the right">
      <div className="space-y-1.5">
        {rows.map((r, i) => (
          <div
            key={i}
            className="grid grid-cols-[1fr_16px_1fr_28px] gap-2 items-center"
          >
            <FieldPicker
              value={r.from}
              onChange={(v) => updateRow(i, { from: v })}
              options={allFields.filter((f) => !usedFromNames.has(f.name) || f.name === r.from)}
              placeholder="old_name"
              variant="tree"
            />
            <span className="text-subtle text-center">→</span>
            <Input
              value={r.to}
              onChange={(e) => updateRow(i, { to: e.target.value })}
              placeholder="new_name"
            />
            <button
              type="button"
              onClick={() => removeRow(i)}
              className="text-subtle hover:text-red text-sm"
              aria-label="Remove mapping"
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={addRow}
          className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
        >
          + Add mapping
        </button>
      </div>
    </Field>
  );
}

const RETYPE_OPTIONS = ["string", "int", "float", "boolean", "date", "timestamp"];

export function RetypeEditor({ step, set }: { step: StepShape; set: Setter }) {
  const allFields = useStepFields();
  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label="Field">
        <FieldPicker
          value={(step.field as string) ?? ""}
          onChange={(v) => set({ field: v })}
          options={allFields}
          variant="tree"
        />
      </Field>
      <Field label="To type">
        <select
          value={(step.to_type as string) ?? "string"}
          onChange={(e) => set({ to_type: e.target.value })}
          className="w-full bg-bg border border-border rounded px-2.5 py-1.5 text-[13.5px] focus:outline-none focus:border-accent"
        >
          {RETYPE_OPTIONS.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </Field>
    </div>
  );
}

export function MapLookupEditor({ step, set }: { step: StepShape; set: Setter }) {
  const allFields = useStepFields();
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Field">
          <FieldPicker
            value={(step.field as string) ?? ""}
            onChange={(v) => set({ field: v })}
            options={allFields}
            variant="tree"
          />
        </Field>
        <Field
          label="Output field (optional)"
          hint="leave blank to overwrite the input column"
        >
          <Input
            value={(step.output_field as string) ?? ""}
            onChange={(e) => set({ output_field: e.target.value || null })}
            placeholder="country_name"
          />
        </Field>
      </div>
      <LookupTablePicker
        value={(step.lookup_id as string) ?? ""}
        onChange={(v) => set({ lookup_id: v })}
      />
    </div>
  );
}

export function MapExpressionEditor({ step, set }: { step: StepShape; set: Setter }) {
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Output field">
          <Input
            value={(step.output_field as string) ?? ""}
            onChange={(e) => set({ output_field: e.target.value })}
            placeholder="cohort_week"
          />
        </Field>
        <Field label="Mode">
          <select
            value={(step.mode as string) ?? "expression"}
            onChange={(e) => set({ mode: e.target.value as "expression" | "calculation" })}
            className="w-full bg-bg border border-border rounded px-2.5 py-1.5 text-[13.5px] focus:outline-none focus:border-accent"
          >
            <option value="expression">expression</option>
            <option value="calculation">calculation</option>
          </select>
        </Field>
      </div>
      <Field label="Expression" hint="SQL expression">
        <Textarea
          value={(step.expr as string) ?? ""}
          onChange={(e) => set({ expr: e.target.value })}
          placeholder="date_trunc('week', created_at)"
        />
        <VariablePickerHint
          onInsert={(token) => set({ expr: ((step.expr as string) ?? "") + token })}
        />
      </Field>
    </div>
  );
}

/** One WHEN/THEN arm on the wire. */
type CaseBranch = { when: string; then: string };

/**
 * Conditional column: CASE WHEN … THEN … ELSE … END.
 *
 * The step dict IS the editor state — `when` is the SQL the rule builder
 * emits, so reopening a saved step just parses each branch back with the same
 * `tryParseBasicSql` the Filter tab uses. THEN values go through safeLiteral;
 * an expression (`THEN other_column`) is not offered here — the raw
 * map/expression step covers that.
 */
export function CaseEditor({ step, set }: { step: StepShape; set: Setter }) {
  const branches = (step.branches as CaseBranch[]) ?? [];

  const setBranches = (next: CaseBranch[]) => set({ branches: next });
  const updateBranch = (i: number, patch: Partial<CaseBranch>) =>
    setBranches(branches.map((b, j) => (j === i ? { ...b, ...patch } : b)));
  const move = (i: number, delta: number) => {
    const j = i + delta;
    if (j < 0 || j >= branches.length) return;
    const next = [...branches];
    [next[i], next[j]] = [next[j]!, next[i]!];
    setBranches(next);
  };

  return (
    <div className="grid gap-3">
      <Field label="Output field" hint="the new column this step adds">
        <Input
          value={(step.output_field as string) ?? ""}
          onChange={(e) => set({ output_field: e.target.value })}
          placeholder="tier"
        />
      </Field>

      {branches.map((b, i) => (
        <div
          key={i}
          className="border border-border rounded-[var(--radius)] p-3 grid gap-2"
        >
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle">
              {i === 0 ? "if" : "else if"}
            </span>
            <div className="flex items-center gap-1.5 text-subtle">
              <button type="button" onClick={() => move(i, -1)}
                className="hover:text-text text-sm" aria-label="Move branch up">↑</button>
              <button type="button" onClick={() => move(i, 1)}
                className="hover:text-text text-sm" aria-label="Move branch down">↓</button>
              <button
                type="button"
                onClick={() => setBranches(branches.filter((_, j) => j !== i))}
                className="hover:text-red text-sm"
                aria-label="Remove branch"
                // The backend requires at least one branch; a step you can't
                // save is worse than a delete button that stops at one.
                disabled={branches.length === 1}
              >×</button>
            </div>
          </div>
          <CaseBranchRules
            when={b.when}
            onWhenChange={(sql) => updateBranch(i, { when: sql })}
          />
          <Field label="Then">
            <Input
              value={displayLiteral(b.then)}
              onChange={(e) => updateBranch(i, { then: safeLiteral(e.target.value) })}
              placeholder="gold"
            />
          </Field>
        </div>
      ))}

      <button
        type="button"
        onClick={() => setBranches([...branches, { when: "", then: "" }])}
        className="justify-self-start font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
      >
        + Add branch
      </button>

      <Field label="Otherwise" hint="left blank, unmatched rows get NULL">
        <Input
          value={displayLiteral((step.otherwise as string | null) ?? "")}
          onChange={(e) =>
            set({ otherwise: e.target.value === "" ? null : safeLiteral(e.target.value) })
          }
          placeholder="bronze"
        />
      </Field>
    </div>
  );
}

/** Rule state for one branch, seeded from the saved SQL on mount. */
function CaseBranchRules({
  when,
  onWhenChange,
}: {
  when: string;
  onWhenChange: (sql: string) => void;
}) {
  const [rules, setRules] = useState<FilterRule[]>(
    () => (when ? tryParseBasicSql(when) : []) ?? [],
  );
  // Branches are keyed by index, so reordering hands this instance a
  // different branch's SQL while its local rules stay put. Re-seed whenever
  // the incoming SQL isn't what we last emitted — the same guarded-effect
  // sync RenameEditor and MapLookup use. An in-progress blank row emits ""
  // and so never trips this.
  useEffect(() => {
    if (rulesToSql(rules) === when) return;
    const parsed = tryParseBasicSql(when);
    if (parsed !== null) setRules(parsed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [when]);

  // SQL too complex to round-trip (hand-written, or edited via the API) —
  // show it rather than silently replacing it with an empty rule list.
  const unparsed = when !== "" && tryParseBasicSql(when) === null;
  if (unparsed) {
    return (
      <Field label="When" hint="hand-written SQL — edit as raw text">
        <Textarea value={when} onChange={(e) => onWhenChange(e.target.value)} />
      </Field>
    );
  }
  return (
    <ConditionRules
      rules={rules}
      onChange={(next) => {
        setRules(next);
        onWhenChange(rulesToSql(next));
      }}
    />
  );
}

export function SortEditor({ step, set }: { step: StepShape; set: Setter }) {
  const allFields = useStepFields();
  const by = (step.by as string[]) ?? [];
  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label="Sort by" hint="fields evaluated in order">
        <FieldMultiSelect
          value={by}
          onChange={(v) => set({ by: v })}
          options={allFields}
          placeholder="add field to sort by…"
          variant="tree"
        />
      </Field>
      <Field label="Direction">
        <select
          value={String(step.ascending ?? true)}
          onChange={(e) => set({ ascending: e.target.value === "true" })}
          className="w-full bg-bg border border-border rounded px-2.5 py-1.5 text-[13.5px] focus:outline-none focus:border-accent"
        >
          <option value="true">ascending</option>
          <option value="false">descending</option>
        </select>
      </Field>
    </div>
  );
}

const AGG_FUNCS = ["sum", "count", "avg", "min", "max", "count_distinct"];

const DATE_PARTS: DatePart[] = [
  "year",
  "quarter",
  "month",
  "week",
  "day",
  "date",
  "dow",
  "hour",
];

interface AggSpec { field: string; func: string; alias: string }

// A group_by entry name (string or the .field of a DatePartGroupBy) is
// considered temporal if the resolved schema type looks like a date/timestamp.
function isTemporalType(t: string | undefined): boolean {
  if (!t) return false;
  const lower = t.toLowerCase();
  return lower.includes("date") || lower.includes("time");
}

export function AggregateEditor({ step, set }: { step: StepShape; set: Setter }) {
  const allFields = useStepFields();
  const group_by = (step.group_by as GroupByEntry[]) ?? [];
  const aggs = (step.aggregations as AggSpec[]) ?? [];

  const fieldType = (name: string): string | undefined => {
    // allFields is flat + deduped by name — matches the shape schema-context builds.
    const found = allFields.find((f) => f.name === name);
    return found?.type;
  };

  const entryField = (e: GroupByEntry) => (typeof e === "string" ? e : e.field);
  const entryPart = (e: GroupByEntry): DatePart | "" =>
    typeof e === "string" ? "" : e.part;

  const updateGroupBy = (i: number, next: GroupByEntry) => {
    const arr = [...group_by];
    arr[i] = next;
    set({ group_by: arr });
  };
  const setEntryField = (i: number, field: string) => {
    const prev = group_by[i];
    if (prev == null) return;
    if (typeof prev === "string") {
      updateGroupBy(i, field);
    } else {
      updateGroupBy(i, { ...prev, field });
    }
  };
  const setEntryPart = (i: number, part: DatePart | "") => {
    const prev = group_by[i];
    if (prev == null) return;
    const field = entryField(prev);
    if (part === "") {
      updateGroupBy(i, field);
    } else {
      updateGroupBy(i, { field, part });
    }
  };
  const addGroupBy = () => set({ group_by: [...group_by, ""] });
  const removeGroupBy = (i: number) =>
    set({ group_by: group_by.filter((_, j) => j !== i) });

  const updateAgg = (i: number, patch: Partial<AggSpec>) => {
    const current = aggs[i];
    if (!current) return;
    const next = [...aggs];
    next[i] = { ...current, ...patch };
    set({ aggregations: next });
  };
  const addAgg = () =>
    set({ aggregations: [...aggs, { field: "", func: "sum", alias: "" }] });
  const removeAgg = (i: number) =>
    set({ aggregations: aggs.filter((_, j) => j !== i) });

  return (
    <div className="grid gap-3">
      <div>
        <div className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle mb-1.5">
          Group by
        </div>
        <div className="grid gap-1.5">
          {group_by.map((entry, i) => {
            const field = entryField(entry);
            const part = entryPart(entry);
            const temporal = isTemporalType(fieldType(field));
            return (
              <div
                key={i}
                className="grid grid-cols-[1fr_140px_28px] gap-2"
              >
                <FieldPicker
                  value={field}
                  onChange={(v) => setEntryField(i, v)}
                  options={allFields}
                  placeholder="field"
                  variant="tree"
                />
                {temporal || part !== "" ? (
                  <select
                    value={part}
                    onChange={(e) =>
                      setEntryPart(i, e.target.value as DatePart | "")
                    }
                    className="bg-bg border border-border rounded px-2.5 py-1.5 text-[13.5px]"
                    title="Extract a date component"
                  >
                    <option value="">(whole value)</option>
                    {DATE_PARTS.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                ) : (
                  <div className="text-subtle text-[11px] flex items-center px-2">
                    {/* Non-temporal field: no part picker */}
                  </div>
                )}
                <button
                  type="button"
                  onClick={() => removeGroupBy(i)}
                  className="text-subtle hover:text-red text-sm"
                >
                  ×
                </button>
              </div>
            );
          })}
        </div>
        <button
          type="button"
          onClick={addGroupBy}
          className="mt-1.5 text-[12px] text-subtle hover:text-fg"
        >
          + add group_by field
        </button>
      </div>
      <div>
        <div className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle mb-1.5">
          Aggregations
        </div>
        <div className="grid gap-1.5">
          {aggs.map((a, i) => (
            <div key={i} className="grid grid-cols-[1fr_120px_1fr_28px] gap-2">
              <FieldPicker
                value={a.field}
                onChange={(v) => updateAgg(i, { field: v })}
                options={allFields}
                placeholder="amount"
                variant="tree"
              />
              <select
                value={a.func}
                onChange={(e) => updateAgg(i, { func: e.target.value })}
                className="bg-bg border border-border rounded px-2.5 py-1.5 text-[13.5px]"
              >
                {AGG_FUNCS.map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </select>
              <Input
                value={a.alias}
                onChange={(e) => updateAgg(i, { alias: e.target.value })}
                placeholder="gmv"
              />
              <button
                type="button"
                onClick={() => removeAgg(i)}
                className="text-subtle hover:text-red text-sm"
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={addAgg}
          className="mt-2 font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
        >
          + Add aggregation
        </button>
      </div>
    </div>
  );
}

/** Left/right operands must resolve to a declared source alias or an
 *  earlier step's `output_id` (plan 056) — offered as a dropdown from
 *  `useJoinOperands()` rather than typed blind. Falls back to a free-text
 *  option for a value that predates this list (e.g. a bare source id from
 *  before the clean break) so it isn't silently discarded. */
function OperandPicker({
  value,
  onChange,
  operands,
}: {
  value: string;
  onChange: (v: string) => void;
  operands: string[];
}) {
  const opts: DropdownOption<string>[] = [
    ...operands.map<DropdownOption<string>>((o) => ({ value: o, label: o })),
    ...(value && !operands.includes(value)
      ? ([{ value, label: `${value} (unresolved)`, disabled: true }] as DropdownOption<string>[])
      : []),
  ];
  return (
    <Dropdown<string>
      value={value}
      onChange={onChange}
      options={opts}
      placeholder="— pick an alias —"
    />
  );
}

type JoinOnValue = string | string[] | Record<string, string>;

function toPairs(value: JoinOnValue | undefined): [string, string][] {
  const entries = typeof value === "object" && value !== null && !Array.isArray(value)
    ? Object.entries(value)
    : [];
  return entries.length ? entries : [["", ""]];
}

/** `on` is same-name (`str`/`str[]`, matched identically on both sides) or
 *  a `{left_col: right_col}` map for a key that isn't named the same on
 *  both sides (e.g. `orders.customer_id` vs `customers.id`) — a composite
 *  mismatched key is just more entries in the map.
 *
 *  Pairs are kept in local state, keyed by array position rather than by
 *  the dict itself: an empty or duplicate left column while typing can't
 *  survive a round-trip through `Record<string, string>` (empty/collided
 *  keys collapse), so — same pattern as `Rename`/`Select` elsewhere in
 *  this file — the editable list lives locally and only well-formed pairs
 *  are pushed up to the pipeline's `on` value. */
function JoinOnEditor({
  value,
  onChange,
  allFields,
}: {
  value: JoinOnValue | undefined;
  onChange: (v: JoinOnValue) => void;
  allFields: SchemaField[];
}) {
  const isPairs = typeof value === "object" && value !== null && !Array.isArray(value);
  const mode: "same" | "different" = isPairs ? "different" : "same";
  const [pairs, setPairs] = useState<[string, string][]>(() => toPairs(value));

  useEffect(() => {
    if (!isPairs) return;
    const emitted = Object.fromEntries(pairs.filter(([l]) => l));
    if (JSON.stringify(emitted) !== JSON.stringify(value ?? {})) {
      setPairs(toPairs(value));
    }
    // Only re-sync when the external value changes — re-running on every
    // local `pairs` edit would fight the transient empty/duplicate state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, isPairs]);

  const setMode = (next: "same" | "different") => {
    if (next === "different") {
      const next_ = toPairs(value);
      setPairs(next_);
      onChange(Object.fromEntries(next_.filter(([l]) => l)));
    } else {
      onChange("");
    }
  };

  const commit = (next: [string, string][]) => {
    setPairs(next);
    onChange(Object.fromEntries(next.filter(([l]) => l)));
  };

  const setPair = (i: number, side: 0 | 1, v: string) => {
    const copy = pairs.map((p) => [...p] as [string, string]);
    copy[i]![side] = v;
    commit(copy);
  };

  const addPair = () => commit([...pairs, ["", ""]]);
  const removePair = (i: number) => commit(pairs.length > 1 ? pairs.filter((_, j) => j !== i) : [["", ""]]);

  return (
    <Field label="On" hint={mode === "same" ? "single field or comma-separated list" : "left column → right column"}>
      <div className="flex flex-col gap-2">
        <Segmented<"same" | "different">
          value={mode}
          onChange={setMode}
          options={[
            { value: "same", label: "Same name" },
            { value: "different", label: "Different names" },
          ]}
        />
        {mode === "same" ? (
          <FieldPicker
            value={Array.isArray(value) ? value.join(", ") : (value as string) ?? ""}
            onChange={(v) => {
              const parts = v.split(",").map((s) => s.trim()).filter(Boolean);
              onChange(parts.length > 1 ? parts : v);
            }}
            options={allFields}
            placeholder="user_id"
            variant="tree"
          />
        ) : (
          <div className="grid gap-1.5">
            {pairs.map(([l, r], i) => (
              <div key={i} className="flex items-center gap-1.5">
                <FieldPicker
                  value={l}
                  onChange={(v) => setPair(i, 0, v)}
                  options={allFields}
                  placeholder="left column"
                  variant="tree"
                />
                <span className="text-subtle text-[12px]">→</span>
                <FieldPicker
                  value={r}
                  onChange={(v) => setPair(i, 1, v)}
                  options={allFields}
                  placeholder="right column"
                  variant="tree"
                />
                {pairs.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removePair(i)}
                    aria-label="Remove column pair"
                    className="text-subtle hover:text-red text-[16px] leading-none px-1"
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
            <button
              type="button"
              onClick={addPair}
              className="font-mono text-[11.5px] text-accent hover:text-accent-h text-left"
            >
              + Add column pair
            </button>
          </div>
        )}
      </div>
    </Field>
  );
}

export function JoinEditor({ step, set }: { step: StepShape; set: Setter }) {
  const allFields = useStepFields();
  const operands = useJoinOperands();
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-3 gap-3">
        <Field label="Left">
          <OperandPicker value={(step.left as string) ?? ""} onChange={(v) => set({ left: v })} operands={operands} />
        </Field>
        <Field label="Right">
          <OperandPicker value={(step.right as string) ?? ""} onChange={(v) => set({ right: v })} operands={operands} />
        </Field>
        <Field label="How">
          <select
            value={(step.how as string) ?? "inner"}
            onChange={(e) => set({ how: e.target.value })}
            className="w-full bg-bg border border-border rounded px-2.5 py-1.5 text-[13.5px]"
          >
            {["inner", "left", "right", "outer"].map((h) => (
              <option key={h} value={h}>{h}</option>
            ))}
          </select>
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <JoinOnEditor
          value={step.on as JoinOnValue | undefined}
          onChange={(v) => set({ on: v })}
          allFields={allFields}
        />
        <Field label="Output id" hint="name of the resulting table in the registry">
          <Input value={(step.output_id as string) ?? ""} onChange={(e) => set({ output_id: e.target.value })} placeholder="joined" />
        </Field>
      </div>
    </div>
  );
}

const PIVOT_AGG = ["sum", "count", "avg", "min", "max"];

export function PivotEditor({ step, set }: { step: StepShape; set: Setter }) {
  const allFields = useStepFields();
  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-3 gap-3">
        <Field label="Index"><FieldPicker value={(step.index as string) ?? ""} onChange={(v) => set({ index: v })} options={allFields} variant="tree" /></Field>
        <Field label="Columns"><FieldPicker value={(step.columns as string) ?? ""} onChange={(v) => set({ columns: v })} options={allFields} variant="tree" /></Field>
        <Field label="Values"><FieldPicker value={(step.values as string) ?? ""} onChange={(v) => set({ values: v })} options={allFields} variant="tree" /></Field>
      </div>
      <Field label="Aggregation">
        <select
          value={(step.agg as string) ?? "sum"}
          onChange={(e) => set({ agg: e.target.value })}
          className="w-full bg-bg border border-border rounded px-2.5 py-1.5 text-[13.5px]"
        >
          {PIVOT_AGG.map((a) => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
      </Field>
    </div>
  );
}

/* --------------- Select — pick/drop fields with optional aliases --------------- */

interface SelectField { field: string; alias?: string | null }

export function SelectEditor({ step, set }: { step: StepShape; set: Setter }) {
  const allFields = useStepFields();
  const fields = (step.fields as SelectField[]) ?? [];
  const dropped = (step.drop as string[]) ?? [];
  const knownNames = allFields.map((f) => f.name);

  // Mode is UI-local so the user can be in drop mode with zero entries
  // (a valid transitional state). Initial mode reflects what's persisted:
  // `drop` non-empty means we opened an existing drop step. Backend
  // enforces mutual exclusion; we mirror that on save.
  const [mode, setMode] = useState<"keep" | "drop">(
    dropped.length > 0 ? "drop" : "keep",
  );

  const keepNames = fields.map((f) => f.field);
  const setKeep = (names: string[]) => {
    const prev = new Map(fields.map((f) => [f.field, f.alias ?? null]));
    set({
      fields: names.map((n) => ({ field: n, alias: prev.get(n) ?? null })),
    });
  };
  const setDropped = (names: string[]) => {
    set({ drop: names });
  };
  const setAlias = (field: string, alias: string) => {
    set({
      fields: fields.map((f) =>
        f.field === field ? { ...f, alias: alias || null } : f,
      ),
    });
  };

  const changeMode = (m: "keep" | "drop") => {
    if (m === mode) return;
    setMode(m);
    // Clear the other list so the step only carries the active-mode data.
    if (m === "keep") set({ drop: [] });
    else set({ fields: [] });
  };

  // Warn only when the current mode would emit an empty step, which the
  // backend rejects (SelectStep requires one of `fields` or `drop`).
  const warn = mode === "keep" ? fields.length === 0 : dropped.length === 0;

  return (
    <div className="grid gap-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle">
          {mode === "keep" ? "keep only listed" : "drop listed, keep the rest"}
        </span>
        <Segmented<"keep" | "drop">
          value={mode}
          onChange={changeMode}
          options={[
            { value: "keep", label: "Select fields" },
            { value: "drop", label: "Drop fields" },
          ]}
        />
      </div>

      {warn && (
        <div className="font-mono text-[11.5px] text-gold px-2.5 py-1.5 border border-gold rounded bg-[color:color-mix(in_srgb,var(--gold)_10%,transparent)]">
          {mode === "keep"
            ? "Pick at least one field, otherwise the pipeline projection is empty and runs will fail."
            : "Add at least one field to drop — the backend rejects an empty select step."}
        </div>
      )}

      {mode === "keep" ? (
        <div className="space-y-3">
          <FieldMultiSelect
            value={keepNames}
            onChange={setKeep}
            options={allFields}
            placeholder="add field to keep…"
            variant="tree"
          />
          {fields.length > 0 && (
            <div className="space-y-1.5">
              <div className="font-mono text-[10.5px] tracking-[0.18em] uppercase text-subtle">
                Aliases (optional)
              </div>
              {fields.map((f) => (
                <div
                  key={f.field}
                  className="grid grid-cols-[1fr_16px_1fr] gap-2 items-center"
                >
                  <span className="font-mono text-[12.5px] text-text px-2.5 py-1.5 border border-border rounded bg-code-bg">
                    {toDisplay(f.field)}
                  </span>
                  <span className="text-subtle text-center">→</span>
                  <Input
                    value={f.alias ?? ""}
                    onChange={(e) => setAlias(f.field, e.target.value)}
                    placeholder={toDisplay(f.field)}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {knownNames.length === 0 ? (
            <p className="font-mono text-[11.5px] text-subtle">
              Infer the source schema first so you can pick which fields to drop.
            </p>
          ) : (
            <>
              <FieldMultiSelect
                value={dropped}
                onChange={setDropped}
                options={allFields}
                placeholder="add field to drop…"
                variant="tree"
              />
              <p className="font-mono text-[11px] text-subtle">
                Drop is applied at run time — fields added to the source later pass through automatically.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/* --------------- Quality check editors --------------- */

type StepEditorProps = { step: StepShape; set: Setter };

function CheckEditor({ step, set }: StepEditorProps) {
  // Basic unless the saved SQL can't round-trip — see FilterEditor.
  const parsedOnMount = useRef<FilterRule[] | null>(
    step.expr ? tryParseBasicSql(step.expr as string) : [],
  );
  const [mode, setMode] = useState<"basic" | "advanced">(
    parsedOnMount.current === null ? "advanced" : "basic",
  );

  const [rules, setRules] = useState<FilterRule[]>(
    () => parsedOnMount.current ?? [],
  );
  const [advancedText, setAdvancedText] = useState<string>(
    (step.expr as string) ?? "",
  );

  const commitRules = (next: FilterRule[]) => {
    setRules(next);
    if (mode === "basic") set({ ...step, expr: rulesToSql(next) });
  };

  const handleAdvancedChange = (text: string) => {
    setAdvancedText(text);
    set({ ...step, expr: text });
  };

  const switchToBasic = () => {
    const parsed = tryParseBasicSql(advancedText);
    if (parsed !== null) {
      setRules(parsed);
      set({ ...step, expr: rulesToSql(parsed) });
    }
    setMode("basic");
  };

  const switchToAdvanced = () => {
    if (advancedText === "") {
      const basicSql = rulesToSql(rules);
      if (basicSql) {
        setAdvancedText(basicSql);
        set({ ...step, expr: basicSql });
      }
    }
    setMode("advanced");
  };

  return (
    <div className="grid gap-3">
      <Field label="Label">
        <Input
          value={(step.label as string) ?? ""}
          onChange={(e) => set({ ...step, label: e.target.value })}
          placeholder="Describe what this assertion checks (optional)"
        />
      </Field>
      <Field label="On failure">
        <Segmented<"fail" | "warn">
          options={[
            { value: "fail", label: "Fail" },
            { value: "warn", label: "Warn" },
          ]}
          value={(step.severity as "fail" | "warn") ?? "fail"}
          onChange={(v) => set({ ...step, severity: v })}
        />
      </Field>
      <div className="flex items-center justify-between">
        <div className="inline-flex border border-border rounded-[var(--radius)] bg-surface p-0.5">
          {(["basic", "advanced"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => {
                if (m === "basic" && mode === "advanced") switchToBasic();
                else if (m === "advanced" && mode === "basic") switchToAdvanced();
              }}
              className={cn(
                "px-3 py-1 text-[12.5px] font-medium rounded-[3px] transition-colors capitalize",
                m === mode
                  ? "bg-[color:var(--accent-tint)] text-accent"
                  : "text-muted hover:text-text",
              )}
            >
              {m}
            </button>
          ))}
        </div>
        <span className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle">
          {mode === "basic" ? "structured · safe" : "raw sql"}
        </span>
      </div>

      {mode === "basic" ? (
        <ConditionRules rules={rules} onChange={commitRules} />
      ) : (
        <Field
          label="Expression"
          hint="raw DuckDB WHERE clause — rows failing this condition are flagged. You are responsible for quoting — for safe, structured input use Basic."
        >
          <Textarea
            value={advancedText}
            onChange={(e) => handleAdvancedChange(e.target.value)}
            placeholder="amount > 0 AND status = 'completed'"
          />
          <VariablePickerHint
            onInsert={(token) => handleAdvancedChange(advancedText + token)}
          />
        </Field>
      )}
    </div>
  );
}

function ProfileEditor({ step, set }: StepEditorProps) {
  const allFields = useStepFields();
  const columns = (step.columns as string[]) ?? [];
  return (
    <div className="flex flex-col gap-2">
      <Field label="Columns" hint="leave empty to profile all columns">
        <FieldMultiSelect
          value={columns}
          onChange={(v) => set({ ...step, columns: v })}
          options={allFields}
          placeholder="all columns (leave empty)"
          variant="tree"
        />
      </Field>
      <p className="font-mono text-[11px] text-subtle">
        Profiles null counts, distinct counts, min/max, and mean for each selected column. Leave empty to profile all columns in the table.
      </p>
    </div>
  );
}

/* ------------------------------- Extract ------------------------------- */

const EXTRACT_PROVIDERS: DropdownOption<string>[] = [
  { value: "pdfplumber", label: "pdfplumber", meta: "word boxes · slower" },
  { value: "pypdf", label: "pypdf", meta: "text only · faster" },
];

const EXTRACT_GRANULARITY: DropdownOption<string>[] = [
  { value: "page", label: "One row per page", meta: "fans out" },
  { value: "document", label: "One row per document", meta: "1:1" },
];

function ExtractEditor({ step, set }: StepEditorProps) {
  const allFields = useStepFields();
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 @lg:grid-cols-2">
        <Field
          label="Path column"
          hint="column holding the file path — a documents source emits `path`"
        >
          <FieldPicker
            value={(step.source_field as string) ?? ""}
            onChange={(v) => set({ ...step, source_field: v })}
            options={allFields}
            placeholder="path"
            variant="tree"
          />
        </Field>
        <Field
          label="Writes to"
          hint="column the extracted text lands in"
        >
          <Input
            value={(step.output_field as string) ?? ""}
            onChange={(e) => set({ ...step, output_field: e.target.value })}
            placeholder="content"
          />
        </Field>
      </div>
      <div className="grid gap-3 @lg:grid-cols-2">
        <Field
          label="Provider"
          hint="pdfplumber returns word bounding boxes, needed to highlight a field back to its place on the page. pypdf is faster and returns text only."
        >
          <Dropdown<string>
            value={(step.provider as string) ?? "pdfplumber"}
            onChange={(v) => set({ ...step, provider: v })}
            options={EXTRACT_PROVIDERS}
          />
        </Field>
        <Field
          label="Granularity"
          hint="page-level fans one document out to one row per page — the usual choice, since it keeps each model call small and gives you a page number for provenance."
        >
          <Dropdown<string>
            value={(step.granularity as string) ?? "page"}
            onChange={(v) => set({ ...step, granularity: v })}
            options={EXTRACT_GRANULARITY}
          />
        </Field>
      </div>
      <p className="font-mono text-[11px] text-subtle">
        Parsed text is cached by file content, so re-running costs nothing and
        editing a downstream Structure step never re-parses the PDFs. A
        document that fails to parse fills <code>extract_meta.error</code> and
        leaves the text NULL — it does not fail the run. Add a Check step if
        you want it fatal.
      </p>
    </div>
  );
}

/* ------------------------------ Structure ------------------------------ */

const STRUCTURE_PROVIDERS: DropdownOption<string>[] = [
  { value: "claude", label: "Claude", meta: "model · costs money" },
  { value: "openai", label: "OpenAI", meta: "model · costs money" },
  { value: "regex", label: "Regex", meta: "deterministic · free" },
];

const FIELD_TYPES: DropdownOption<string>[] = [
  { value: "string", label: "string" },
  { value: "int", label: "int" },
  { value: "float", label: "float" },
  { value: "boolean", label: "boolean" },
  { value: "date", label: "date" },
  { value: "timestamp", label: "timestamp" },
];

const ON_ERROR: DropdownOption<string>[] = [
  { value: "null", label: "Null the row", meta: "run continues" },
  { value: "fail", label: "Fail the run", meta: "stops everything" },
];

const emptyModelField = (): DataModelField => ({
  name: "",
  type: "string",
  description: "",
  required: false,
});

function StructureEditor({ step, set }: StepEditorProps) {
  const allFields = useStepFields();
  const model = (step.model as { fields?: DataModelField[]; instructions?: string }) ?? {};
  const fields = model.fields ?? [];
  const provider = (step.provider as string) ?? "claude";
  const params = (step.params as Record<string, unknown>) ?? {};

  const setModel = (patch: Partial<{ fields: DataModelField[]; instructions: string }>) =>
    set({ ...step, model: { ...model, ...patch } });

  const updateField = (i: number, patch: Partial<DataModelField>) => {
    const copy = [...fields];
    const current = copy[i];
    if (!current) return;
    copy[i] = { ...current, ...patch };
    setModel({ fields: copy });
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 @lg:grid-cols-2">
        <Field label="Reads from" hint="column holding the extracted text">
          <FieldPicker
            value={(step.input_field as string) ?? ""}
            onChange={(v) => set({ ...step, input_field: v })}
            options={allFields}
            placeholder="content"
            variant="tree"
          />
        </Field>
        <Field
          label="Provider"
          hint="regex is free, offline, and gives exact provenance — use it for anything with a reliable pattern. Models are for the fields where pattern matching cannot work."
        >
          <Dropdown<string>
            value={provider}
            onChange={(v) => set({ ...step, provider: v })}
            options={STRUCTURE_PROVIDERS}
          />
        </Field>
      </div>

      {provider !== "regex" && (
        <Field
          label="Model"
          hint="leave empty for the provider default (claude-opus-5 / gpt-5). Sampling settings like temperature are rejected by these models — steer with field descriptions instead."
        >
          <Input
            value={(params.model as string) ?? ""}
            onChange={(e) => {
              const next = { ...params };
              if (e.target.value) next.model = e.target.value;
              else delete next.model;
              set({ ...step, params: next });
            }}
            placeholder="claude-opus-5"
          />
        </Field>
      )}

      <div className="flex flex-col gap-2">
        <div className="font-mono text-[10.5px] tracking-[0.15em] uppercase text-subtle">
          Fields to extract
        </div>
        {fields.map((f, i) => (
          <div
            key={i}
            className="flex flex-col gap-1.5 rounded border border-border bg-code-bg px-2.5 py-2"
          >
            <div className="flex items-start gap-1.5">
              <Input
                value={f.name}
                onChange={(e) => updateField(i, { name: e.target.value })}
                placeholder="invoice_total"
                className="basis-[180px] grow"
              />
              <div className="w-[130px] shrink-0">
                <Dropdown<string>
                  value={f.type}
                  onChange={(v) => updateField(i, { type: v as DataModelField["type"] })}
                  options={FIELD_TYPES}
                />
              </div>
              <button
                type="button"
                onClick={() => setModel({ fields: fields.filter((_, j) => j !== i) })}
                className="w-[28px] shrink-0 pt-1.5 text-subtle hover:text-red text-sm"
                aria-label="Remove field"
              >
                ×
              </button>
            </div>
            <Input
              value={f.description}
              onChange={(e) => updateField(i, { description: e.target.value })}
              placeholder="what this field is, in the document's own words"
            />
            {provider === "regex" && (
              <Input
                value={f.pattern ?? ""}
                onChange={(e) => updateField(i, { pattern: e.target.value || null })}
                placeholder="Total:\s*\$?([\d,.]+)     ← capture group 1 is the value"
              />
            )}
          </div>
        ))}
        <button
          type="button"
          onClick={() => setModel({ fields: [...fields, emptyModelField()] })}
          className="self-start font-mono text-[10.5px] tracking-[0.15em] uppercase text-accent hover:text-accent-h"
        >
          + Add field
        </button>
        {fields.length === 0 && (
          <p className="font-mono text-[11px] text-red">
            At least one field is required — with none the step produces no
            columns.
          </p>
        )}
      </div>

      <Field
        label="Instructions"
        hint="optional, applies to the whole document. Put per-field guidance in that field's description instead."
      >
        <Textarea
          value={model.instructions ?? ""}
          onChange={(e) => setModel({ instructions: e.target.value })}
          placeholder="These are freight invoices. Amounts are in USD unless a currency is printed next to them."
        />
      </Field>

      <Field
        label="On error"
        hint="what happens when one document fails to structure"
      >
        <Dropdown<string>
          value={(step.on_error as string) ?? "null"}
          onChange={(v) => set({ ...step, on_error: v })}
          options={ON_ERROR}
        />
      </Field>

      <p className="font-mono text-[11px] text-subtle">
        Each field above becomes a real typed column. From here on the row is
        ordinary tabular data — filter, join, aggregate and check all work on
        it unchanged.
      </p>
    </div>
  );
}

export function StepEditor({ step, set }: { step: StepShape; set: Setter }) {
  switch (step.op) {
    case "filter":    return <FilterEditor step={step} set={set} />;
    case "rename":    return <RenameEditor step={step} set={set} />;
    case "retype":    return <RetypeEditor step={step} set={set} />;
    case "map":       return step.mode === "lookup"
      ? <MapLookupEditor step={step} set={set} />
      : <MapExpressionEditor step={step} set={set} />;
    case "case":      return <CaseEditor step={step} set={set} />;
    case "sort":      return <SortEditor step={step} set={set} />;
    case "aggregate": return <AggregateEditor step={step} set={set} />;
    case "join":      return <JoinEditor step={step} set={set} />;
    case "pivot":     return <PivotEditor step={step} set={set} />;
    case "select":    return <SelectEditor step={step} set={set} />;
    case "check":     return <CheckEditor step={step} set={set} />;
    case "profile":   return <ProfileEditor step={step} set={set} />;
    case "extract":   return <ExtractEditor step={step} set={set} />;
    case "structure": return <StructureEditor step={step} set={set} />;
  }
}
