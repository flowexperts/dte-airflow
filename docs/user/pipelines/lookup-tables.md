# Lookup tables

A **lookup table** is a small reference table you attach to a pipeline — think country code → country name, product SKU → product line.

Manage them under **Lookup tables** in the sidebar.

## When to reach for one

Use a lookup table when:

- The mapping is small (dozens to a few thousand entries).
- It changes rarely, and you'd rather edit it once here than in every pipeline.
- You want to keep the pipeline focused on data flow, not spelling out translations.

If the mapping is big or lives somewhere authoritative (a database, a Google sheet), read it as a real source and use a **Join** step instead.

## Create one

**Lookup tables → New**. Give it an id and a name. Add rows — a **key** and a **value** per row.

## Use one in a pipeline

Add a **Map · lookup** step. Pick:

- **Field** — the column in your data that holds the key (e.g. `country_code`)
- **Lookup table** — the one you just created
- **Output field** — where the looked-up value should land (e.g. `country_name`). Leave empty to overwrite the input field.

When a row's key doesn't appear in the lookup table, the output column is empty for that row.
