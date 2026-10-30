# Lookup tables

A **lookup table** is a small reference table you attach to a pipeline: country code → country name, or product SKU → product line.

Manage them under **Admin ▸ DTE Lookup tables** in Airflow.

## When to reach for one

Use a lookup table when:

- The mapping is small (dozens to a few thousand entries).
- It changes rarely, and you'd rather edit it once here than in every pipeline.
- You want to keep the pipeline focused on data flow instead of spelling out translations.

If the mapping is big or lives somewhere authoritative (a database or a spreadsheet export), read it as a real source and use a **Join** step instead.

## Create one

Go to **Admin ▸ DTE Lookup tables ▸ New**. Give it an id and a name, then add rows: a **key** and a **value** per row.

## Use one in a pipeline

Add a **Map · lookup** step and pick:

- **Field**: the column in your data that holds the key (e.g. `country_code`)
- **Lookup table**: the one you just created
- **Output field**: where the looked-up value lands (e.g. `country_name`). Leave it empty to overwrite the input field.

When a row's key isn't in the lookup table, the output column is empty for that row.
