# Building a pipeline

Pipelines live under **Plugins ▸ DTE Pipelines ▸ Transform** in Airflow's left rail. Click **New pipeline** to open the builder.

## The form

- **Id**: required. Use letters, numbers, `_` and `-`. It names the Airflow DAG (`dte__<id>`) and appears in run history. There's no rename, so pick something you'll keep.
- **Name**: required. A human-readable label you can change any time.
- **Sources**: at least one. Pick from saved sources, or add one inline.
- **Destination**: exactly one. Pick from saved destinations, or add one inline.
- **Steps**: zero or more, in order.

Save is blocked until the id, the name, at least one source and a destination are filled in, and until every **Select / Drop fields** step has at least one field.

## Sources panel

There's one card per source. Reorder with ↑/↓, remove with ✕, and add another with **+ New source**.

The **Edit** button on a source opens the source editor inline. Remember that sources are shared: editing one here affects every pipeline that uses it, and the form warns you about that.

dte infers each source's schema as you build. If a field picker is empty, click **Infer schema** on the source card. Every field picker in the builder fills in from what it finds.

## Destination picker

It's the same shape as a source card, but takes one value. JSON file destinations edit inline. Every other type lives under **Admin ▸ DTE Destinations** and you pick it by name here.

## Steps panel

**Add step** opens a menu of every op (see [Steps](../steps/index.md)). Each step has its own small editor. Reorder with ↑/↓ and remove with ✕.

For a database destination, **Auto-map** on the steps panel proposes a column mapping from your source fields to the target table's columns. You tick the matches you want, and it adds one ordinary **Select / Drop fields** step.

## Save, revisions and the DAG

**Save** checks that the sources and destination exist and match their connections, and that no step is obviously broken. Errors show up in a red panel naming the specific field.

Every save is a new **revision**, listed on the pipeline's **History** tab. Airflow's dag-processor picks up the change within seconds. Each run records the exact revision it ran.

## Next

- [Preview & run](preview-and-run.md)
- [Scheduling](scheduling.md)
- [Field names](field-refs.md)
- [Lookup tables](lookup-tables.md)
