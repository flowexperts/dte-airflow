"use client";

import { useEffect, useRef } from "react";
import { useSchemas } from "@/components/builder/schema-context";
import { pipelineStepSchemas, type Pipeline, type SourceTableRef } from "@/lib/api";

/* Field autocomplete needs the same two background syncs BuilderForm runs.
 * They live inside BuilderForm today; lifted here so any surface that mounts a
 * step editor gets working field pickers. */

/** Source schemas, fetched once per pipeline source ref — keyed by `alias`,
 *  not `source_id`, so a two-table pipeline off one source gets two distinct
 *  field sets instead of one overwriting the other. */
export function AutoInferSchemas({ sources }: { sources: SourceTableRef[] }) {
  const { schemas, refreshById } = useSchemas();
  const inflight = useRef<Set<string>>(new Set());
  useEffect(() => {
    for (const ref of sources) {
      if (!ref.source_id || !ref.alias) continue;
      const key = ref.alias;
      if (inflight.current.has(key) || schemas[key]) continue;
      inflight.current.add(key);
      refreshById(ref.source_id, ref.alias, ref.table);
    }
  }, [sources, schemas, refreshById]);
  return null;
}

/**
 * Per-step output schemas, so a step's field picker offers the columns
 * produced by the steps above it. Debounced; compile errors are swallowed so
 * autocomplete keeps its last-known good answer while you type.
 */
export function AutoStepSchemas({ pipeline }: { pipeline: Pipeline }) {
  const { setPerStepSchemas } = useSchemas();
  const seq = useRef(0);
  const key = JSON.stringify(pipeline);

  useEffect(() => {
    if (
      !pipeline.sources ||
      pipeline.sources.length === 0 ||
      (pipeline.steps ?? []).length === 0
    ) {
      setPerStepSchemas({});
      return;
    }
    const my = ++seq.current;
    const t = window.setTimeout(async () => {
      try {
        const res = await pipelineStepSchemas(pipeline);
        if (seq.current !== my) return;
        const numeric: Record<number, string[]> = {};
        for (const [k, v] of Object.entries(res.step_schemas)) {
          numeric[Number(k)] = v;
        }
        setPerStepSchemas(numeric);
      } catch {
        // Partially-typed pipelines don't compile; keep the last good schemas.
      }
    }, 500);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `key` captures pipeline
  }, [key, setPerStepSchemas]);

  return null;
}
