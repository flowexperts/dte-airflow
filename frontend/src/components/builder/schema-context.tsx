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
}

const SchemaContext = createContext<SchemaState | null>(null);

export function SchemaProvider({ children }: { children: ReactNode }) {
  const [schemas, setSchemas] = useState<Record<string, SchemaEntry>>({});

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

  return (
    <SchemaContext.Provider value={{ schemas, refresh, refreshById, allFields }}>
      {children}
    </SchemaContext.Provider>
  );
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
