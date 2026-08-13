"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import {
  getSourceSchema,
  inferSchema,
  type Source,
  type SchemaField,
} from "@/lib/api";
import { SYSTEM_COLUMNS } from "@/lib/system-columns";

interface SchemaEntry {
  fields: SchemaField[];
  loading: boolean;
  error: string | null;
}

interface SchemaState {
  schemas: Record<string, SchemaEntry>;
  refresh: (source: Source) => Promise<void>;
  refreshById: (id: string) => Promise<void>;
  allFields: SchemaField[];
  /** Column names produced at each step index (plan 038 item 7).
   *  Keys are numeric step indexes; values are the columns *output* by
   *  that step. Populated by callers via `setPerStepSchemas` — typically
   *  from `POST /api/pipelines/step-schemas`. */
  perStepSchemas: Record<number, string[]>;
  setPerStepSchemas: (next: Record<number, string[]>) => void;
  /** Fields visible to the editor at step index N.
   *
   *  - N === 0: only source fields (allFields).
   *  - N >= 1: fields produced by step index-1 if known, else fall back
   *    to allFields so autocomplete never disappears completely.
   *
   *  Returns `SchemaField[]` shape so it drops into `FieldPicker` /
   *  `FieldMultiSelect` wherever `allFields` was used. */
  fieldsAtStep: (index: number) => SchemaField[];
}

const SchemaContext = createContext<SchemaState | null>(null);

export function SchemaProvider({ children }: { children: ReactNode }) {
  const [schemas, setSchemas] = useState<Record<string, SchemaEntry>>({});
  const [perStepSchemas, setPerStepSchemas] = useState<
    Record<number, string[]>
  >({});

  const _apply = useCallback((id: string, fn: () => Promise<{ fields: SchemaField[] }>) => {
    setSchemas((prev) => ({
      ...prev,
      [id]: { fields: prev[id]?.fields ?? [], loading: true, error: null },
    }));
    return fn()
      .then(({ fields }) => {
        setSchemas((prev) => ({
          ...prev,
          [id]: { fields, loading: false, error: null },
        }));
      })
      .catch((e: unknown) => {
        setSchemas((prev) => ({
          ...prev,
          [id]: {
            fields: prev[id]?.fields ?? [],
            loading: false,
            error: e instanceof Error ? e.message : String(e),
          },
        }));
      });
  }, []);

  const refresh = useCallback(
    async (source: Source) => {
      if (!source.id) return;
      await _apply(source.id, () => inferSchema(source));
    },
    [_apply],
  );

  const refreshById = useCallback(
    async (id: string) => {
      if (!id) return;
      await _apply(id, () => getSourceSchema(id));
    },
    [_apply],
  );

  const allFields = useMemo(() => {
    const seen = new Map<string, SchemaField>();
    const walk = (fields: SchemaField[], prefix: string[] = []) => {
      for (const f of fields) {
        const path = [...prefix, f.name];
        if (f.children && f.children.length) {
          walk(f.children, path);
        } else {
          const name = path.join(".");
          if (!seen.has(name)) seen.set(name, { name, type: f.type });
        }
      }
    };
    for (const entry of Object.values(schemas)) walk(entry.fields);
    return Array.from(seen.values());
  }, [schemas]);

  const fieldsAtStep = useCallback(
    (index: number): SchemaField[] => {
      if (index <= 0) return allFields;
      const cols = perStepSchemas[index - 1];
      if (!cols || cols.length === 0) return allFields;
      // Preserve the type hint from allFields when the column name matches
      // a source field (e.g. group_by columns pass through unchanged); new
      // aggregation aliases fall back to "unknown".
      const typeByName = new Map(allFields.map((f) => [f.name, f.type]));
      return cols
        // System columns are carried by the compiler and cannot be dropped
        // by a projection, so offering them as pickable fields would be
        // offering a choice that has no effect. Hidden, not removed — the
        // data is still on every row.
        .filter((name) => !SYSTEM_COLUMNS.has(name))
        .map((name) => ({
          name,
          type: typeByName.get(name) ?? "unknown",
        }));
    },
    [allFields, perStepSchemas],
  );

  return (
    <SchemaContext.Provider
      value={{
        schemas,
        refresh,
        refreshById,
        allFields,
        perStepSchemas,
        setPerStepSchemas,
        fieldsAtStep,
      }}
    >
      {children}
    </SchemaContext.Provider>
  );
}

/* ---------------- Step index context (plan 038 item 7) ----------------
 *
 * StepsPanel wraps each step's editor in <StepIndexContext value={i}> so
 * downstream `useStepFields()` can pick the right field set without every
 * editor threading `stepIndex` through its props.
 */
const StepIndexContext = createContext<number>(0);

export function StepIndexProvider({
  index,
  children,
}: {
  index: number;
  children: ReactNode;
}) {
  return (
    <StepIndexContext.Provider value={index}>{children}</StepIndexContext.Provider>
  );
}

/** Fields available to the editor at the current step index. Falls back
 *  to `allFields` when no per-step schema is known (e.g. the pipeline
 *  hasn't been dry-run yet). */
export function useStepFields(): SchemaField[] {
  const idx = useContext(StepIndexContext);
  const { fieldsAtStep } = useSchemas();
  return fieldsAtStep(idx);
}

export function useSchemas() {
  const ctx = useContext(SchemaContext);
  if (!ctx) throw new Error("useSchemas must be used inside <SchemaProvider>");
  return ctx;
}

/** Returns null when no <SchemaProvider> is above — useful for components
 *  reused on standalone pages (e.g. /sources/new) where schema inference
 *  isn't wired up. */
export function useSchemasOptional() {
  return useContext(SchemaContext);
}
