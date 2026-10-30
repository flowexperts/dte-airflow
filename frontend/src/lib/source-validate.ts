/** A new source has no id field: the server generates one from a blank id. */
export function validateSource(source: { id: string }, mode: "create" | "edit"): string | null {
  if (mode === "create") return null;
  if (!source.id.trim()) return "Source id is required.";
  if (!/^[a-zA-Z0-9_-]+$/.test(source.id))
    return "Source id may only contain letters, numbers, '_' and '-'.";
  return null;
}
