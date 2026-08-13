/** Columns the product carries, not the user.
 *
 *  Mirrors `SYSTEM_COLUMNS` in `dte/compiler/ibis_compiler.py`, which refuses
 *  to let a `select` drop them — `artifact_ref` points at the source
 *  document, `extract_meta.key` at the cached parse holding the word boxes,
 *  `structure_meta` at per-field provenance.
 *
 *  Because they cannot be projected away, the UI is what keeps them out of
 *  sight: hidden from the builder's field pickers (a pickable field that
 *  cannot be dropped is a choice with no effect) and from output tables (four
 *  columns of hashes and JSON blobs would bury the data the user came for).
 *
 *  Hidden, never stripped. The row still carries them, which is exactly what
 *  lets the Inspect action work on a table that does not display them.
 */
export const SYSTEM_COLUMNS: ReadonlySet<string> = new Set([
  "artifact_ref",
  "extract_meta",
  "structure_meta",
  "block_index",
]);

/** Column names to render, in their original order, minus the plumbing. */
export function visibleColumns(columns: readonly string[]): string[] {
  return columns.filter((c) => !SYSTEM_COLUMNS.has(c));
}
