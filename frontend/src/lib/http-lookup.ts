/** `{column}` placeholders in an `http_lookup` URL, in order, deduped.
 *  Same pattern the backend renders with (`_URL_PLACEHOLDER_RE`). */
export function urlPlaceholders(url: string): string[] {
  const seen = new Set<string>();
  for (const m of url.matchAll(/\{([^{}]+)\}/g)) {
    if (m[1]) seen.add(m[1]);
  }
  return [...seen];
}

/** Placeholders that name no column available at this step. Empty when the
 *  schema is unknown, so an un-inferred source never shows a false alarm. */
export function missingPlaceholders(url: string, columns: string[]): string[] {
  if (columns.length === 0) return [];
  const have = new Set(columns);
  return urlPlaceholders(url).filter((p) => !have.has(p));
}
