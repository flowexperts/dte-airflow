import { useSchemasOptional } from "./schema-context";
import { unfilteredPartitions } from "@/lib/metered";

/**
 * Plan 093: a partitioned warehouse table with no filter on its partition
 * column is a full-table scan on every run — on `pypi.file_downloads` that is
 * 1.4 PB. Sits under the steps panel head, where the filter that fixes it is
 * added. Renders nothing for unpartitioned sources.
 */
export function PartitionHint({ steps }: { steps: Array<{ op?: string; expr?: unknown }> }) {
  const ctx = useSchemasOptional();
  if (!ctx) return null;
  const missing = Object.entries(ctx.schemas).flatMap(([alias, entry]) =>
    unfilteredPartitions(entry.partitionColumns ?? [], steps).map((col) => ({ alias, col })),
  );
  if (missing.length === 0) return null;
  return (
    <div className="px-3.5 py-2 border-b border-border text-[12px] text-gold">
      {missing.map(({ alias, col }) => (
        <div key={`${alias}.${col}`}>
          No filter on <code className="font-mono">{col}</code> ({alias}) — this run scans the whole
          table. Add a filter on it.
        </div>
      ))}
    </div>
  );
}
