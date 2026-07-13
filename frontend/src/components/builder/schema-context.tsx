"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { inferSchema, type DltSource, type SchemaField } from "@/lib/api";

interface SchemaEntry {
  fields: SchemaField[];
  loading: boolean;
  error: string | null;
}

interface SchemaState {
  schemas: Record<string, SchemaEntry>;
  refresh: (source: DltSource) => Promise<void>;
  allFields: SchemaField[];
}

const SchemaContext = createContext<SchemaState | null>(null);

export function SchemaProvider({ children }: { children: ReactNode }) {
  const [schemas, setSchemas] = useState<Record<string, SchemaEntry>>({});

  const refresh = useCallback(async (source: DltSource) => {
    const id = source.id;
    if (!id) return;
    setSchemas((prev) => ({
      ...prev,
      [id]: { fields: prev[id]?.fields ?? [], loading: true, error: null },
    }));
    try {
      const { fields } = await inferSchema(source);
      setSchemas((prev) => ({
        ...prev,
        [id]: { fields, loading: false, error: null },
      }));
    } catch (e) {
      setSchemas((prev) => ({
        ...prev,
        [id]: {
          fields: prev[id]?.fields ?? [],
          loading: false,
          error: e instanceof Error ? e.message : String(e),
        },
      }));
    }
  }, []);

  const allFields = useMemo(() => {
    // Flatten STRUCT children into dot-form leaves so the flat-variant
    // pickers still see a searchable list. The tree picker rebuilds the
    // hierarchy from these dot-form names in `buildTree`.
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
    <SchemaContext.Provider value={{ schemas, refresh, allFields }}>
      {children}
    </SchemaContext.Provider>
  );
}

export function useSchemas() {
  const ctx = useContext(SchemaContext);
  if (!ctx) throw new Error("useSchemas must be used inside <SchemaProvider>");
  return ctx;
}
