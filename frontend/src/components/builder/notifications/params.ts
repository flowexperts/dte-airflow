/** A notifier's constructor kwargs ⇄ one text field per argument. Text stays
 *  text; a value that parses as a JSON list or object (`cc`, `blocks`, …) is
 *  sent as one. Blank fields are left out, so the notifier's default applies. */
export function fromFields(fields: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, raw] of Object.entries(fields)) {
    const v = raw.trim();
    if (!v) continue;
    out[k] = v;
    if (v.startsWith("[") || v.startsWith("{")) {
      try {
        out[k] = JSON.parse(v);
      } catch {
        // not JSON: plain text that happens to start with a bracket
      }
    }
  }
  return out;
}

export function toFields(params: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(params).map(([k, v]) => [k, typeof v === "string" ? v : JSON.stringify(v)]),
  );
}
