import type { BulkDeleteResult } from "./api";

function describeReferencedBy(refs: unknown): string {
  if (Array.isArray(refs)) return `pipelines: ${refs.join(", ")}`;
  if (refs && typeof refs === "object") {
    const parts: string[] = [];
    for (const [k, v] of Object.entries(refs as Record<string, unknown>)) {
      if (Array.isArray(v) && v.length > 0) parts.push(`${k}: ${v.join(", ")}`);
    }
    return parts.join(" | ") || "unknown";
  }
  return String(refs);
}

export function summarizeBulkDelete(kind: string, r: BulkDeleteResult): string {
  const lines: string[] = [];
  lines.push(`Deleted ${r.deleted.length} ${kind}(s).`);
  if (r.not_found.length > 0) {
    lines.push(`Not found: ${r.not_found.join(", ")}`);
  }
  if (r.blocked.length > 0) {
    lines.push(`Blocked (${r.blocked.length}):`);
    for (const b of r.blocked) {
      lines.push(`  • ${b.id} — ${describeReferencedBy(b.referenced_by)}`);
    }
  }
  return lines.join("\n");
}
