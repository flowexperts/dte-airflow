/** Turning an output row back into something the inspector can show.
 *
 *  An extracted row carries three separate references to the same document:
 *  `artifact_ref` (the document's own hash), `extract_meta.key` (the cached
 *  parse, which is where the word boxes live), and `structure_meta.fields`
 *  (per-field provenance). This assembles them, and returns `null` for any
 *  row that is not backed by a document — most rows in most pipelines.
 */

import type { Provenance } from "./provenance";

export interface InspectableRow {
  docKey: string;
  extractKey: string | null;
  page: number;
  fields: { name: string; value: unknown; provenance: Provenance | null }[];
  filename: string | null;
}

const ARTIFACT_REF = /^artifact:\/\/([0-9a-f]{64})$/;

/** JSON columns arrive as strings from DuckDB and as objects once something
 *  upstream has parsed them. Accept both, and never throw: this runs inside a
 *  table renderer, where one malformed row must not blank the whole preview. */
function asObject(v: unknown): Record<string, unknown> | null {
  if (v && typeof v === "object") return v as Record<string, unknown>;
  if (typeof v === "string") {
    try {
      const parsed = JSON.parse(v);
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch {
      return null;
    }
  }
  return null;
}

export function inspectableRow(row: Record<string, unknown>): InspectableRow | null {
  const ref = typeof row.artifact_ref === "string" ? row.artifact_ref : "";
  const match = ARTIFACT_REF.exec(ref);
  const docKey = match?.[1];
  if (!docKey) return null;

  const extractMeta = asObject(row.extract_meta);
  const extractKey =
    typeof extractMeta?.key === "string" ? extractMeta.key : null;

  const structureMeta = asObject(row.structure_meta);
  const provenance = asObject(structureMeta?.fields) ?? {};

  // Driven by the declared fields, not by the row's columns: a field that
  // came back null is still a field, and it is the one a user most wants to
  // look at — they are asking why nothing was found.
  const fields = Object.keys(provenance).map((name) => ({
    name,
    value: row[name] ?? null,
    provenance: (asObject(provenance[name]) as Provenance | null) ?? null,
  }));

  const page = Number(row.page);

  return {
    docKey,
    extractKey,
    page: Number.isFinite(page) && page > 0 ? page : 1,
    fields,
    filename: typeof row.filename === "string" ? row.filename : null,
  };
}
