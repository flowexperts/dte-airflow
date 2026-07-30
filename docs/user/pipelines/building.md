# Building a pipeline

Pipelines live under **Pipelines** in the sidebar. Click **New** to open the builder.

## The form

- **Id** — required. Short, letters/numbers/underscores. This appears in URLs and run history. There's no rename today, so pick something you'll keep.
- **Name** — required. Human label.
- **Sources** — at least one. Pick from saved sources, or add one inline.
- **Destination** — exactly one. Pick from saved destinations, or add one inline.
- **Steps** — zero or more, in order.

Save is blocked until id, name, at least one source, and a destination are filled in — and any Select step has at least one field checked.

## Sources panel

One card per source. Reorder with ↑/↓, remove with ✕, add another with **+ New source**.

The **Edit** button on a source opens the source editor inline. Remember: sources are shared. Editing here affects every pipeline that uses that source. The form warns you.

Every source card has an **Infer schema** button. Do this before you build steps — the field pickers throughout the builder fill in from what Infer schema found.

## Destination picker

Same shape as a source card, single-value. JSON file destinations edit inline; other types live under **Destinations** and get picked by name here.

## Steps panel

**Add step** → menu with the nine ops (see [Steps](../steps/index.md)). Each step has its own small editor. Reorder with ↑/↓; remove with ✕.

## Save and validation

**Save** checks:

- Id and name filled in
- All source ids exist and their connections match
- The destination id exists and its connection matches
- No empty Select step

Errors show up in a red panel with the specific field. Fix and save again.

## Next

- [Preview & run](preview-and-run.md)
- [Field names](field-refs.md)
- [Lookup tables](lookup-tables.md)
